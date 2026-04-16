#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""
s01_agent_loop_qwen.py - The Agent Loop (Qwen3.5 适配版本)

核心模式与原版完全一致，仅适配 Qwen/OpenAI API 格式：

    while finish_reason == "tool_calls":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

适配要点：
1. Anthropic messages.create() → OpenAI chat.completions.create()
2. response.stop_reason → response.choices[0].finish_reason
3. response.content 数组 → message.content + message.tool_calls
4. role="user" + tool_result → role="tool" + tool_call_id
"""

import os
import subprocess
import json

from openai import OpenAI  # 改为 OpenAI 客户端（Qwen 兼容 OpenAI 格式）
from dotenv import load_dotenv

# 加载环境变量（从 .env 文件读取配置）
load_dotenv(override=True)

# ========== 客户端配置（Qwen 适配） ==========
# 使用阿里云百炼平台的 OpenAI 兼容接口
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),  # 阿里云 API Key
    base_url=os.getenv("DASHSCOPE_BASE_URL"),  # 兼容端点
)

# 模型名称：可选择 qwen-plus / qwen-max / qwen-turbo 等
MODEL = os.getenv("QWEN_MODEL_ID", "qwen-plus")

# 系统提示词：告诉模型它的身份和能力
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# ========== 工具定义（OpenAI 格式） ==========
# Anthropic 格式：{name, description, input_schema}
# OpenAI 格式：{type: "function", function: {name, description, parameters}}
TOOLS = [
    {
        "type": "function",  # OpenAI 要求指定类型
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {  # 对应 Anthropic 的 input_schema
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"],
            },
        }
    }
]


def run_bash(command: str) -> str:
    """
    执行 bash 命令的安全包装
    与原版完全一致，无需修改
    """
    # 危险命令拦截
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    
    try:
        # 执行命令，120秒超时
        r = subprocess.run(
            command, 
            shell=True, 
            cwd=os.getcwd(),
            capture_output=True, 
            text=True, 
            timeout=120
        )
        # 合并 stdout 和 stderr
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"  # 截断超长输出
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


# ========== 核心 Agent 循环（Qwen 适配版） ==========
def agent_loop(messages: list):
    """
    核心循环：持续调用模型，直到模型不再要求使用工具
    
    适配变化：
    - Anthropic: client.messages.create() → OpenAI: client.chat.completions.create()
    - Anthropic: response.stop_reason → OpenAI: response.choices[0].finish_reason
    - Anthropic: "tool_use" → OpenAI: "tool_calls"
    """
    while True:
        # 1. 调用模型（OpenAI API 格式）
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,  # 系统消息放最前
            tools=TOOLS,  # 可用工具列表
            tool_choice="auto",  # 让模型自动决定是否调用工具
            max_tokens=8000,
        )
        
        # 2. 获取模型的消息对象（OpenAI 格式不同点）
        message = response.choices[0].message
        
        # 3. 构建助手消息记录（适配 OpenAI 格式）
        # Anthropic: response.content 是数组，包含 text 和 tool_use 块
        # OpenAI: message.content 是字符串，tool_calls 是单独字段
        assistant_msg = {
            "role": "assistant",
            "content": message.content or ""  # 文本内容（可能为 None）
        }
        
        # 如果有工具调用，需要记录 tool_calls 字段（OpenAI 特有）
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments  # JSON 字符串
                    }
                } for tc in message.tool_calls
            ]
        
        # 将助手回复加入历史
        messages.append(assistant_msg)
        
        # 4. 检查停止原因（关键适配点）
        # Anthropic: response.stop_reason 值为 "tool_use" | "end_turn" | "max_tokens"
        # OpenAI: response.choices[0].finish_reason 值为 "tool_calls" | "stop" | "length"
        finish_reason = response.choices[0].finish_reason
        
        # 如果模型没有调用工具（finish_reason != "tool_calls"），结束循环
        if finish_reason != "tool_calls":
            return
        
        # 5. 执行工具调用（Qwen 适配版）
        # Anthropic: 遍历 response.content 数组，找 type == "tool_use" 的块
        # OpenAI: 遍历 message.tool_calls 数组
        results = []
        
        for tool_call in message.tool_calls:
            # 解析工具名和参数
            name = tool_call.function.name
            
            # OpenAI 的参数是 JSON 字符串，需要解析
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            
            # 只处理 bash 工具（本例只有一个工具）
            if name == "bash":
                command = arguments.get("command", "")
                print(f"\033[33m$ {command}\033[0m")  # 黄色显示命令
                
                # 执行命令
                output = run_bash(command)
                print(output[:200])  # 打印前200字符
                
                # 6. 构建工具结果（关键格式差异）
                # Anthropic: {"type": "tool_result", "tool_use_id": "...", "content": "..."}
                # OpenAI: {"role": "tool", "tool_call_id": "...", "content": "..."}
                results.append({
                    "role": "tool",  # OpenAI 特有角色
                    "tool_call_id": tool_call.id,  # 对应调用的 ID
                    "content": output
                })
        
        # 7. 将工具结果加入历史（OpenAI 格式要求）
        # Anthropic: 作为一条 role="user" 的消息，content 是数组
        # OpenAI: 每条工具结果是独立的 role="tool" 消息
        # 注意：Qwen 也支持将多个 tool 结果合并，但标准做法是多条消息
        for result in results:
            messages.append(result)
        
        # 继续循环，让模型基于工具结果决定下一步


# ========== 主程序入口 ==========
if __name__ == "__main__":
    history = []  # 对话历史，跨轮次保持上下文
    
    while True:
        try:
            # 青色提示符
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        
        # 退出命令
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        # 用户输入加入历史
        history.append({"role": "user", "content": query})
        
        # 运行 Agent 循环
        agent_loop(history)
        
        # 打印最终回复（适配 OpenAI 格式）
        # Anthropic: history[-1]["content"] 是数组，包含 text 块
        # OpenAI: history[-1]["content"] 是字符串，或者需要检查 tool_calls
        last_msg = history[-1]
        response_content = last_msg.get("content", "")
        
        # 如果是字符串直接打印
        if isinstance(response_content, str) and response_content:
            print(response_content)
        # 如果是列表（兼容处理，理论上 OpenAI 不会这样）
        elif isinstance(response_content, list):
            for block in response_content:
                if isinstance(block, str):
                    print(block)
                elif hasattr(block, "text"):
                    print(block.text)
        
        print()  # 空行分隔