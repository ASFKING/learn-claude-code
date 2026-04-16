#!/usr/bin/env python3
# Harness: tool dispatch -- expanding what the model can reach.
"""
s02_tool_use.py - Tools

The agent loop from s01 didn't change. We just added tools to the array
and a dispatch map to route calls.

    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+

Key insight: "The loop didn't change at all. I just added tools."
与原版 s02 完全一致：Agent 循环本身不变，只是增加了更多工具和工具分发机制。

【与 Anthropic 版本的主要区别】
1. 客户端：Anthropic() → OpenAI()（千问兼容 OpenAI 格式）
2. API：messages.create() → chat.completions.create()
3. 工具定义格式：{name, input_schema} → {type: "function", function: {...}}
4. 响应解析：response.content[] → response.choices[0].message.tool_calls[]
5. 工具结果：{type: "tool_result"} → {role: "tool"}
"""

import os
import subprocess
from pathlib import Path
import json
from openai import OpenAI  # 【区别1】使用 OpenAI 客户端（千问兼容此格式）
from dotenv import load_dotenv

load_dotenv(override=True)

# ========== 客户端配置 ==========
# 【区别2】Anthropic 使用 base_url 参数，OpenAI 在初始化时设置
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),      # 阿里云百炼 API Key
    base_url=os.getenv("DASHSCOPE_BASE_URL"),     # 兼容端点
)
MODEL = os.getenv("QWEN_MODEL_ID", "qwen-plus")
WORKDIR = Path.cwd()

# 【区别3】Anthropic 版本通过 system 参数传入，OpenAI 版本放入 messages 列表
SYSTEM = f"""You are a coding agent at {WORKDIR}. 
Use tools to solve tasks. Act, don't explain.
Available tools: bash, read_file, write_file, edit_file"""

# ========== 工具函数（与原版完全一致，无需修改） ==========
def safe_path(p: str) -> Path:
    """安全检查：确保路径不逃离工作目录（与原版完全一致）"""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """安全执行 Bash 命令（与原版完全一致）"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """安全读取文件内容（与原版完全一致）"""
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """写入文件（自动创建父目录）（与原版完全一致）"""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """精确文本替换（查找 old_text 替换为 new_text）（与原版完全一致）"""
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ========== 工具分发映射表（与原版完全一致） ==========
# 【核心设计】通过映射表路由工具调用，新增工具只需加到这里和 TOOLS 列表
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}
# ========== 工具定义（OpenAI/Qwen 格式） ==========
# 【区别4】Anthropic 格式 vs OpenAI 格式对比：
#
# Anthropic 格式：
#   {"name": "bash", "description": "...", "input_schema": {...}}
#
# OpenAI/Qwen 格式：
#   {
#     "type": "function",
#     "function": {
#       "name": "bash",
#       "description": "...",
#       "parameters": {...}  # 对应 Anthropic 的 input_schema
#     }
#   }
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    }
]


# ========== 核心 Agent 循环（Qwen 适配版） ==========
def agent_loop(messages: list):
    """
    核心循环：持续调用模型，直到模型不再要求使用工具
    
    【与 Anthropic 版本的关键区别】
    
    1. API 调用方式：
       Anthropic: client.messages.create(model=MODEL, system=SYSTEM, ...)
       OpenAI:    client.chat.completions.create(model=MODEL, ...)
                  # system 消息需手动加入 messages 列表
    
    2. 响应结构：
       Anthropic: response.stop_reason (值为 "tool_use" | "end_turn")
       OpenAI:    response.choices[0].finish_reason (值为 "tool_calls" | "stop")
    
    3. 工具调用数据位置：
       Anthropic: response.content[] 数组，元素 type 为 "tool_use"
       OpenAI:    response.choices[0].message.tool_calls[] 数组
    
    4. 工具调用信息提取：
       Anthropic: block.name, block.input (已解析的字典)
       OpenAI:    tc.function.name, json.loads(tc.function.arguments) (JSON字符串需解析)
    
    5. 工具调用 ID：
       Anthropic: block.id
       OpenAI:    tc.id
    
    6. 工具结果格式：
       Anthropic: {"type": "tool_result", "tool_use_id": "...", "content": "..."}
       OpenAI:    {"role": "tool", "tool_call_id": "...", "content": "..."}
    """
    while True:
        # 【区别5】API 调用：Anthropic 的 messages.create() → OpenAI 的 chat.completions.create()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,  # system 消息放最前
            tools=TOOLS,
            tool_choice="auto",  # 让模型自动决定是否调用工具
            max_tokens=8000,
        )
        
        # 【区别6】获取消息对象：Anthropic 直接用 response，OpenAI 需 response.choices[0].message
        message = response.choices[0].message
        
        # 构建助手消息记录
        assistant_msg = {
            "role": "assistant",
            "content": message.content or ""  # 文本内容（可能为 None）
        }
        
        # 【区别7】工具调用记录方式不同
        # Anthropic: 直接记录在 response.content 数组中
        # OpenAI: 需要单独记录 tool_calls 字段
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
        
        messages.append(assistant_msg)
        
        # 【区别8】检查停止原因
        # Anthropic: response.stop_reason == "tool_use"
        # OpenAI:    response.choices[0].finish_reason == "tool_calls"
        finish_reason = response.choices[0].finish_reason
        
        if finish_reason != "tool_calls":  # 模型没有调用工具，结束循环
            return
        
        # 【区别9】执行工具调用
        results = []
        
        # Anthropic: for block in response.content:
        #               if block.type == "tool_use":
        # OpenAI: for tool_call in message.tool_calls:
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            
            # 【区别10】参数解析：Anthropic 的 block.input 是字典，OpenAI 的是 JSON 字符串
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            
            # 使用 TOOL_HANDLERS 分发执行（与原版完全一致）
            handler = TOOL_HANDLERS.get(name)
            if handler:
                output = handler(**arguments)
                print(f"\033[33m> {name}: {output[:200]}\033[0m")
            else:
                output = f"Unknown tool: {name}"
            
            # 【区别11】工具结果格式
            # Anthropic: {"type": "tool_result", "tool_use_id": block.id, "content": output}
            # OpenAI:    {"role": "tool", "tool_call_id": tool_call.id, "content": output}
            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output
            })
        
        # 将工具结果加入历史（OpenAI 每条结果是独立消息）
        for result in results:
            messages.append(result)
        
        # 继续循环，让模型基于工具结果决定下一步


# ========== 主程序入口（与 s01_qwen 一致） ==========
if __name__ == "__main__":
    history = []
    
    while True:
        try:
            query = input("\033[36ms02 >> \033[0m")  # 青色提示符
        except (EOFError, KeyboardInterrupt):
            break
        
        if query.strip().lower() in ("q", "exit", ""):
            break
        
        history.append({"role": "user", "content": query})
        agent_loop(history)
        
        # 打印最终回复
        last_msg = history[-1]
        response_content = last_msg.get("content", "")
        
        if isinstance(response_content, str) and response_content:
            print(response_content)
        elif isinstance(response_content, list):
            for block in response_content:
                if isinstance(block, str):
                    print(block)
                elif hasattr(block, "text"):
                    print(block.text)
        
        print()