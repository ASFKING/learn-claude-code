#!/usr/bin/env python3
# Harness: planning -- keeping the model on course without scripting the route.
"""
s03_todo_write_qwen.py - TodoWrite（Qwen3.5 适配版本）

【核心思想】
与原版 s03 完全一致：模型通过 TodoManager 跟踪自己的进度，系统通过"唠叨提醒"机制
强制模型在忘记更新时保持任务状态同步。

【与 Anthropic 版本的主要区别】
1. 客户端：Anthropic() → OpenAI()（千问兼容 OpenAI 格式）
2. API：messages.create() → chat.completions.create()
3. 系统消息传递方式不同
4. 工具定义格式：input_schema → parameters
5. 响应解析：response.content[] → response.choices[0].message.tool_calls[]
6. 工具结果格式：{type: "tool_result"} → {role: "tool"}
7. 提醒消息格式：{type: "text"} → 普通字符串消息
"""

from typing import Any
import os
import subprocess
import json
from pathlib import Path

from openai import OpenAI  # 【区别1】使用 OpenAI 客户端（千问兼容此格式）
from dotenv import load_dotenv

load_dotenv(override=True)

# ========== 客户端配置 ==========
# 【区别2】Anthropic 使用 base_url 参数，OpenAI 在初始化时设置
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),      # 阿里云百炼 API Key
    base_url=os.getenv("DASHSCOPE_BASE_URL"),     # 兼容端点
)

MODEL = os.getenv("QWEN_MODEL_ID", "qwen-plus")   # 千问模型ID
WORKDIR = Path.cwd()

# 【区别3】Anthropic 版本通过 system 参数传入，OpenAI 版本放入 messages 列表
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""


# ========== TodoManager: 结构化状态管理（与原版完全一致） ==========
class TodoManager:
    """
    待办事项管理器：LLM 通过 todo 工具写入状态，系统跟踪进度
    
    状态标记：
    [ ] pending     - 待处理
    [>] in_progress - 进行中（同时只能有一个）
    [x] completed   - 已完成
    """
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """验证并更新待办列表"""
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        
        validated = []
        in_progress_count = 0
        
        for i, item in enumerate(items):
            # 提取字段
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            
            # 验证
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            
            validated.append({"id": item_id, "text": text, "status": status})
        
        # 约束：同时只能有一个进行中任务
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        
        self.items = validated
        return self.render()

    def render(self) -> str:
        """渲染待办列表为可读格式"""
        if not self.items:
            return "No todos."
        
        lines = []
        for item in self.items:
            marker = {
                "pending": "[ ]", 
                "in_progress": "[>]", 
                "completed": "[x]"
            }[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


# 全局 TodoManager 实例
TODO = TodoManager()


# ========== 工具函数（与原版完全一致） ==========

def safe_path(p: str) -> Path:
    """安全检查：确保路径不逃离工作目录（与原版完全一致）"""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """执行 shell 命令（与原版完全一致）"""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, timeout=120
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """读取文件内容，支持行数限制（与原版完全一致）"""
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """写入文件（自动创建父目录）（与原版完全一致）"""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
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


# ========== 工具分发映射表（新增 todo 工具） ==========
# 【核心设计】通过映射表路由工具调用
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),  # 新增：待办管理
}


# ========== 工具定义（OpenAI/Qwen 格式） ==========
# 【区别4】Anthropic 格式 vs OpenAI 格式对比：
#
# Anthropic 格式：
#   {"name": "todo", "description": "...", "input_schema": {...}}
#
# OpenAI/Qwen 格式：
#   {
#     "type": "function",
#     "function": {
#       "name": "todo",
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
    },
    {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Update task list. Track progress on multi-step tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"]
                                }
                            },
                            "required": ["id", "text", "status"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    }
]


# ========== Agent 循环（带唠叨提醒）（Qwen 适配版） ==========
def agent_loop(messages: list):
    """
    核心循环：持续调用模型，直到模型不再要求使用工具
    
    【特殊机制 - 唠叨提醒】
    如果连续 3 轮没有更新 todo，系统会插入提醒消息强制模型更新进度
    
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
       Anthropic: {"type": "tool_result", "tool_use_id": block.id, "content": "..."}
       OpenAI:    {"role": "tool", "tool_call_id": tc.id, "content": "..."}
    
    7. 提醒消息格式：
       Anthropic: {"type": "text", "text": "<reminder>..."} 作为 content 数组元素
       OpenAI:    普通字符串消息 {"role": "user", "content": "<reminder>..."}
    """
    rounds_since_todo = 0  # 记录距离上次更新 todo 的轮数
    
    while True:
        # 【区别5】API 调用：Anthropic 的 messages.create() → OpenAI 的 chat.completions.create()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,  # system 消息放最前
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=8000,
        )
        
        # 【区别6】获取消息对象：Anthropic 直接用 response，OpenAI 需 response.choices[0].message
        message = response.choices[0].message
        
        # 构建助手消息记录
        assistant_msg = {
            "role": "assistant",
            "content": message.content or ""
        }
        
        # 【区别7】工具调用记录方式不同
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
        used_todo = False  # 标记本轮是否使用了 todo 工具
        
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
            
            # 使用 TOOL_HANDLERS 分发执行
            handler = TOOL_HANDLERS.get(name)
            try:
                if handler:
                    output = handler(**arguments)
                else:
                    output = f"Unknown tool: {name}"
            except Exception as e:
                output = f"Error: {e}"
            
            print(f"\033[33m> {name}: {str(output)[:200]}\033[0m")
            
            # 【区别11】工具结果格式
            # Anthropic: {"type": "tool_result", "tool_use_id": block.id, "content": str(output)}
            # OpenAI:    {"role": "tool", "tool_call_id": tool_call.id, "content": str(output)}
            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(output)
            })
            
            # 检查是否使用了 todo 工具
            if name == "todo":
                used_todo = True
        
        # 更新计数器：如果用了 todo 则重置，否则累加
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        
        # 【区别12】唠叨提醒格式
        # Anthropic: results.insert(0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"})
        # OpenAI:    results.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"})
        # 注意：OpenAI 格式中，提醒需要作为独立的消息角色，而不是 content 数组中的 type 字段
        if rounds_since_todo >= 3:
            # 在 OpenAI 格式中，提醒作为普通 user 消息追加到 results 中
            # 但由于 results 是工具结果列表，我们需要在下一轮循环前单独插入提醒
            # 这里改为在 messages 中直接插入提醒消息
            messages.append({
                "role": "user", 
                "content": "<reminder>Update your todos.</reminder>"
            })
            rounds_since_todo = 0  # 重置计数器，避免重复提醒
            continue  # 跳过本轮 results 追加，直接开始下一轮（让模型先看到提醒）
        
        # 将工具结果加入历史
        for result in results:
            messages.append(result)
        
        # 继续循环


# ========== 主程序入口 ==========
if __name__ == "__main__":
    history = []
    
    while True:
        try:
            query = input("\033[36ms03 >> \033[0m")  # 青色提示符
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