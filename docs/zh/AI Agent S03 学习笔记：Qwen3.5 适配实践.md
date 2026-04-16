# LLM 编码助手工具系统学习笔记

> 基于 Qwen/Anthropic 适配版 TodoWrite 系统的深度解析
> 分析对象：`s03_todo_write_qwen.py`

---

## 目录

1. [系统架构总览](#一系统架构总览)
2. [核心设计理念](#二核心设计理念)
3. [三层工具定义体系](#三三层工具定义体系)
4. [TodoManager 状态管理](#四todomanager-状态管理)
5. [Agent 执行循环](#五agent-执行循环)
6. [模型决策机制](#六模型决策机制)
7. [保障机制详解](#七保障机制详解)
8. [Anthropic vs OpenAI 适配差异](#八anthropic-vs-openai-适配差异)
9. [关键代码片段](#九关键代码片段)
10. [最佳实践总结](#十最佳实践总结)

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                      用户输入层                          │
│                    (命令行交互界面)                         │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                      Agent 循环层                         │
│              (agent_loop - 核心调度逻辑)                   │
│         持续调用模型 → 执行工具 → 返回结果 → 循环           │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│                      工具执行层                            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  │  bash   │ │ read_   │ │ write_  │ │ edit_   │        │
│  │         │ │  file   │ │  file   │ │  file   │        │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │
│                           ┌─────────┐                    │
│                           │  todo   │  ← 核心创新点        │
│                           │ (状态)   │                    │
│                           └─────────┘                    │
└─────────────────────────────────────────────────────────┘
```

---

## 二、核心设计理念

### 2.1 显式优于隐式

不让模型"默默思考"，强制通过 `todo` 工具写下待办事项，所有任务进度可视化，人类可观测。

### 2.2 约束即自由

限制同时只能有一个 `in_progress` 任务，强制单线程思考，避免并行任务导致的混乱。

### 2.3 可观测性

通过 todo 工具，人类可以看到模型的"内心独白"，状态流转清晰可见：`[ ]` → `[>]` → `[x]`。

### 2.4 防御性编程

- 路径检查防止目录遍历攻击
- 危险命令过滤（`rm -rf /`, `sudo` 等）
- 超时控制（120秒）

### 2.5 适配层模式

核心逻辑与 API 细节分离，便于移植到不同 LLM 提供商（Anthropic/OpenAI/Qwen）。

---

## 三、三层工具定义体系

### 3.1 第一层：Python 函数实现（实际执行）

| 函数 | 功能 | 安全机制 |
|:---|:---|:---|
| `run_bash` | 执行 shell 命令 | 危险命令黑名单、超时控制 |
| `run_read` | 读取文件内容 | `safe_path` 路径检查 |
| `run_write` | 写入文件 | 自动创建父目录 |
| `run_edit` | 精确文本替换 | 查找验证，不存在则报错 |
| `TodoManager.update` | 更新任务状态 | 四层验证机制 |

```python
def safe_path(p: str) -> Path:
    """安全检查：确保路径不逃离工作目录"""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

### 3.2 第二层：工具分发映射表（路由层）

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}
```

**设计优点**：

- 解耦：工具定义与实现分离
- 可扩展：新增工具只需添加一行
- 灵活：lambda 可做参数转换

### 3.3 第三层：LLM 可见的 JSON Schema（描述层）

```python
TOOLS = [
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
```

**Schema 设计原则**：

| 字段 | 作用 | 最佳实践 |
|:---|:---|:---|
| `name` | 工具标识 | 与 `TOOL_HANDLERS` 的 key 一致 |
| `description` | **最关键**：告诉模型何时使用 | 包含使用场景，如 "Use this when..." |
| `parameters.properties` | 参数列表及类型 | 每个参数加 `description` 解释含义 |
| `required` | 必填参数 | 强制模型必须提供，避免遗漏 |
| `enum` | 枚举限制 | 限制状态值，防止模型乱写 |

---

## 四、TodoManager 状态管理

### 4.1 状态机设计

```
┌─────────┐    开始执行     ┌─────────┐    完成      ┌─────────┐
│ pending │ ─────────────→ │in_progre│ ───────────→ │completed│
│  [ ]    │                │  [>]    │              │  [x]    │
└─────────┘                └─────────┘              └─────────┘
    ↑                                                  │
    └────────────────  重置/重新打开 ────────────────────┘
```

### 4.2 四层验证体系

```python
def update(self, items: list) -> str:
    # 约束 1：最多 20 个任务
    if len(items) > 20:
        raise ValueError("Max 20 todos allowed")

    # 约束 2：必须有描述
    if not text:
        raise ValueError(f"Item {item_id}: text required")

    # 约束 3：状态必须是三者之一
    if status not in ("pending", "in_progress", "completed"):
        raise ValueError(f"Item {item_id}: invalid status '{status}'")

    # 约束 4：同时只能有一个进行中（最关键）
    if in_progress_count > 1:
        raise ValueError("Only one task can be in_progress at a time")
```

### 4.3 可视化渲染

```python
def render(self) -> str:
    marker = {
        "pending": "[ ]",      # 空格：待办
        "in_progress": "[>]",    # >：箭头表示进行
        "completed": "[x]"     # x：完成
    }[item["status"]]
```

**输出示例**：

```
[>] #1: 创建项目结构
[ ] #2: 编写 app.py
[ ] #3: 创建模板文件夹

(0/3 completed)
```

---

## 五、Agent 执行循环

### 5.1 完整数据流

```
用户输入
    │
    ▼
┌─────────────────┐
│  组装请求        │
│  - system 提示   │
│  - 历史消息      │
│  - tools 定义    │
│  - tool_choice   │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  模型决策        │
│  分析意图 → 匹配工具描述 → 生成调用   │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  解析工具调用    │
│  - 提取 name     │
│  - 解析 arguments│
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  TOOL_HANDLERS  │
│     路由分发     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  执行 Python 函数│
│  返回字符串结果   │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  结果加入历史    │
│  循环或结束      │
└─────────────────┘
```

### 5.2 核心代码结构

```python
def agent_loop(messages: list):
    rounds_since_todo = 0  # 唠叨提醒计数器

    while True:
        # 1. 调用模型
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=8000,
        )

        message = response.choices[0].message

        # 2. 检查是否调用工具
        if not message.tool_calls:
            return  # 没有工具调用，结束循环

        # 3. 执行每个工具调用
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)

            handler = TOOL_HANDLERS[name]
            output = handler(**arguments)

            # 检查结果加入历史
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(output)
            })

            # 更新唠叨计数器
            if name == "todo":
                used_todo = True

        # 4. 唠叨提醒机制
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": "<reminder>Update your todos.</reminder>"
            })
            rounds_since_todo = 0
```

---

## 六、模型决策机制

### 6.1 决策因素权重

| 优先级 | 因素 | 说明 |
|:---|:---|:---|
| 1 | 用户输入的显式指令 | "用 bash 查看当前目录" → 明确调用 bash |
| 2 | 系统提示的引导 | SYSTEM = "Use the todo tool to plan..." |
| 3 | 工具描述的匹配度 | description 与任务的相关性 |
| 4 | 对话历史的上下文 | 上一轮创建了 todo → 这一轮应该更新状态 |

### 6.2 系统提示的关键作用

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""
```

**指令拆解**：

- `"Use the todo tool to plan multi-step tasks"` → **必须使用**
- `"Mark in_progress before starting"` → **开始前的动作**
- `"completed when done"` → **完成后的动作**
- `"Prefer tools over prose"` → **别光说不练**

---

## 七、保障机制详解

### 7.1 软性引导：系统提示

告诉模型"应该做什么"，依赖模型的指令遵循能力。

### 7.2 硬性约束：状态机验证

```python
# 状态枚举限制
"enum": ["pending", "in_progress", "completed"]

# 单进行中约束
if in_progress_count > 1:
    raise ValueError("Only one task can be in_progress at a time")
```

### 7.3 纠偏机制：唠叨提醒（Nagging）

```python
rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

if rounds_since_todo >= 3:
    messages.append({
        "role": "user",
        "content": "<reminder>Update your todos.</reminder>"
    })
```

**为什么需要？**

| 轮次 | 无提醒 | 有提醒 |
|:---|:---|:---|
| 1 | 创建 todo | 创建 todo |
| 2 | 写代码（忘更新） | 写代码（忘更新） |
| 3 | 写代码（忘更新） | 写代码（忘更新） |
| 4 | 写代码（忘更新） | **触发提醒！** |
| 5 | 混乱/重复 | 模型更新 todo |
| 6 | - | 继续正确执行 |

### 7.4 可视化反馈：自我纠正

- 每次 todo 更新后返回渲染结果
- 模型看到 `(1/3 completed)` 感知进度
- 看到 `[>]` 标记知道当前焦点

### 7.5 错误反馈：试错学习

- 非法状态 → 返回错误信息 → 模型修正
- 多进行中 → 拒绝更新 → 模型重新决策

---

## 八、Anthropic vs OpenAI 适配差异

| 特性 | Anthropic | OpenAI/Qwen |
|:---|:---|:---|
| **客户端** | `Anthropic()` | `OpenAI()` |
| **API 方法** | `messages.create()` | `chat.completions.create()` |
| **系统消息** | `system=SYSTEM` 参数 | 放入 `messages` 列表首位 |
| **工具定义** | `input_schema` | `parameters` |
| **响应结构** | `response.content[]` | `response.choices[0].message` |
| **停止原因** | `response.stop_reason` | `response.choices[0].finish_reason` |
| **工具调用位置** | `response.content[].type == "tool_use"` | `response.choices[0].message.tool_calls[]` |
| **参数格式** | `block.input` (已解析的字典) | `tc.function.arguments` (JSON 字符串) |
| **工具调用 ID** | `block.id` | `tc.id` |
| **工具结果格式** | `{"type": "tool_result", ...}` | `{"role": "tool", ...}` |
| **提醒消息** | `{"type": "text", ...}` | 普通字符串消息 `{"role": "user", ...}` |

### 关键适配代码对比

**Anthropic 版本**：

```python
response = client.messages.create(
    model=MODEL,
    system=SYSTEM,  # 独立参数
    messages=messages,
    tools=TOOLS,
)
```

**OpenAI/Qwen 版本**：

```python
response = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "system", "content": SYSTEM}] + messages,  # 放入列表
    tools=TOOLS,
    tool_choice="auto",
)
```

---

## 九、关键代码片段

### 9.1 工具执行路由

```python
# 解析模型输出的工具调用
for tool_call in message.tool_calls:
    name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)

    # 路由到对应处理函数
    handler = TOOL_HANDLERS.get(name)
    if handler:
        output = handler(**arguments)
    else:
        output = f"Unknown tool: {name}"

    # 结果返回给模型
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": str(output)
    })
```

### 9.2 完整的状态验证

```python
def update(self, items: list) -> str:
    """验证并更新待办列表"""
    if len(items) > 20:
        raise ValueError("Max 20 todos allowed")

    validated = []
    in_progress_count = 0

    for i, item in enumerate(items):
        text = str(item.get("text", "")).strip()
        status = str(item.get("status", "pending")).lower()
        item_id = str(item.get("id", str(i + 1)))

        if not text:
            raise ValueError(f"Item {item_id}: text required")
        if status not in ("pending", "in_progress", "completed"):
            raise ValueError(f"Item {item_id}: invalid status '{status}'")
        if status == "in_progress":
            in_progress_count += 1

        validated.append({"id": item_id, "text": text, "status": status})

    if in_progress_count > 1:
        raise ValueError("Only one task can be in_progress at a time")

    self.items = validated
    return self.render()
```

### 9.3 唠叨提醒实现

```python
# 初始化计数器
rounds_since_todo = 0

# 每轮检查
used_todo = False
for tool_call in message.tool_calls:
    if tool_call.function.name == "todo":
        used_todo = True

# 更新计数器
rounds_since_todo = 0 if used_todo else rounds_since_todo + 1

# 触发提醒
if rounds_since_todo >= 3:
    messages.append({
        "role": "user",
        "content": "<reminder>Update your todos.</reminder>"
    })
    rounds_since_todo = 0
    continue  # 让模型先看到提醒
```

---

## 十、最佳实践总结

### 10.1 工具设计原则

| 原则 | 说明 | 示例 |
|:---|:---|:---|
| **描述具体化** | 包含使用场景 | `"Use this when you need to..."` |
| **约束明确化** | 用 `required` 和 `enum` | `"enum": ["pending", "in_progress", "completed"]` |
| **命名语义化** | 参数名清晰 | `old_text` vs `old` |
| **单一职责** | 一个工具做一件事 | `read_file` 只读，`write_file` 只写 |

### 10.2 状态管理原则

- **状态机要简单**：三态足够，不要过度设计
- **约束要强制**：代码层面验证，不只是提示
- **反馈要及时**：每次更新立即返回可视化结果
- **纠错要主动**：模型会遗忘，系统要主动提醒

### 10.3 系统架构原则

- **分层解耦**：实现层、路由层、描述层分离
- **防御编程**：假设模型会犯错，做好验证
- **可观测性**：状态可视化，人类可理解
- **适配隔离**：核心逻辑与 API 细节分离

### 10.4 人机协作契约

| 角色 | 职责 |
|:---|:---|
| **人类开发者** | 设计清晰的工具描述、系统提示、约束规则 |
| **LLM 模型** | 根据上下文自主决策何时调用工具 |
| **系统代码** | 验证输入、强制执行规则、提供反馈 |
| **提醒机制** | 在模型"遗忘"时及时纠正 |

---

## 参考资源

- 原始代码：`s03_todo_write_qwen.py`
- 设计思想来源：Anthropic 的 "Building effective agents"
- 适配目标：阿里云通义千问（Qwen）OpenAI 兼容 API

---

*生成时间：2026-04-16*
*分析对象：LLM 编码助手工具系统*
