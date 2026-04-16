# Python Agent 基础：工具系统与任务管理

本文档整理自 s02_tool_use.py 和 s03_todo_write.py 的代码分析，涵盖 Python 基础知识和 Agent 架构设计。

---

## 目录

1. [整体架构](#一整体架构)
2. [模块导入系统](#二模块导入系统)
3. [环境变量与配置](#三环境变量与配置)
4. [f-string 字符串格式化](#四f-string-字符串格式化)
5. [类型注解](#五类型注解)
6. [pathlib 路径处理](#六pathlib-路径处理)
7. [异常处理](#七异常处理)
8. [字典与查找表模式](#八字典与查找表模式)
9. [lambda 函数与参数解包](#九lambda-函数与参数解包)
10. [类与面向对象](#十类与面向对象)
11. [列表推导式与生成器](#十一列表推导式与生成器)
12. [TodoManager 任务管理](#十二todomanager-任务管理)
13. [工具分发系统](#十三工具分发系统)

---

## 一、整体架构

### s02_tool_use.py：无工具的简单循环

```
用户输入 → LLM 决策 → 调用工具 → 执行工具 → 返回结果 → 完成
```

核心代码：约 340 行，实现 4 个工具（bash, read_file, write_file, edit_file）

### s03_todo_write.py：增加任务规划能力

```
用户输入 → LLM 决策 → 调用工具 → 执行工具 → 检查Todo → 提醒机制
              ↑__________________________________|
                      ↑
              TodoManager (任务状态)
```

核心改进：Agent 可以规划多步骤任务，并跟踪自己的进度

---

## 二、模块导入系统

```python
import os                           # 操作系统模块
import subprocess                  # 执行系统命令
from pathlib import Path            # 现代化路径处理
import json                         # JSON 数据解析
from openai import OpenAI           # OpenAI API 客户端
from dotenv import load_dotenv      # 加载 .env 环境变量
```

### import 的三种方式

| 方式 | 示例 | 使用方法 |
|------|------|----------|
| 导入整个模块 | `import os` | `os.getenv()` |
| 从模块导入特定内容 | `from pathlib import Path` | `Path()` |
| 导入并起别名 | `import numpy as np` | `np.array()` |

---

## 三、环境变量与配置

```python
load_dotenv(override=True)  # 加载 .env 文件

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),      # 获取环境变量
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
)

MODEL = os.getenv("QWEN_MODEL_ID", "qwen-plus")  # 带默认值
WORKDIR = Path.cwd()                              # 当前工作目录
```

### os.getenv() 用法

```python
# 语法：os.getenv(key, default=None)
api_key = os.getenv("DASHSCOPE_API_KEY")              # 不存在返回 None
model = os.getenv("QWEN_MODEL_ID", "qwen-plus")       # 不存在返回默认值
```

---

## 四、f-string 字符串格式化

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use tools to solve tasks."""
```

### f-string 基础用法

```python
name = "Alice"
age = 25

# 基础替换
print(f"Hello, {name}!")           # Hello, Alice!

# 表达式计算
print(f"Next year: {age + 1}")     # Next year: 26

# 调用方法
print(f"Upper: {name.upper()}")    # Upper: ALICE
```

### 与 Java 对比

```java
// Java 字符串拼接
String msg = "Hello, " + name + "!";

// Java 15+ 文本块
String msg = """
    Hello, %s!
    Age: %d
    """.formatted(name, age);
```

---

## 五、类型注解

```python
def safe_path(p: str) -> Path:
    """安全检查：确保路径不逃离工作目录"""
    path = (WORKDIR / p).resolve()
    return path
```

### 类型注解语法

```python
# 基本语法：参数: 类型, 返回值 -> 类型
def add(x: int, y: int) -> int:
    return x + y

# 复杂类型（需导入 typing）
from typing import List, Dict, Optional

def process(items: List[str]) -> Dict[str, int]:
    ...

def find(user_id: int) -> Optional[str]:
    return None if not found else name
```

**注意**：类型注解只是提示，Python 不会强制检查！

---

## 六、pathlib 路径处理

```python
from pathlib import Path

WORKDIR = Path.cwd()                    # 获取当前工作目录

p = Path("/home/user") / "docs" / "file.txt"  # 用 / 拼接路径！

# 常用方法
p.exists()              # 是否存在
p.is_file()             # 是否是文件
p.is_dir()              # 是否是目录
p.read_text()           # 读取文本内容
p.write_text("hello")   # 写入文本
p.parent                # 父目录
p.name                  # 文件名
p.suffix                # 扩展名（如 .txt）
```

### 与 Java 对比

```java
// Java NIO.2
Path p = Paths.get("/home/user", "docs", "file.txt");
boolean exists = Files.exists(p);
String content = Files.readString(p);
```

---

## 七、异常处理

```python
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"

    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
```

### 关键语法

#### any() + 生成器表达式

```python
# 检查列表中是否有任意元素满足条件
any(d in command for d in dangerous)

# 等价于
for d in dangerous:
    if d in command:
        return True
return False
```

#### 三元表达式

```python
# Python
return out[:50000] if out else "(no output)"

# Java
return out != null ? out.substring(0, 50000) : "(no output)";
```

#### try/except 结构

```python
try:
    # 可能出错的代码
    result = risky_operation()
except SpecificError:
    # 处理特定异常
    handle_error()
except Exception as e:
    # 捕获所有其他异常
    print(f"Error: {e}")
else:
    # 可选：没有异常时执行
    print("Success!")
finally:
    # 可选：无论是否异常都执行
    cleanup()
```

---

## 八、字典与查找表模式

### 基础字典操作

```python
person = {"name": "Alice", "age": 25}

# 访问
person["name"]          # Alice（不存在会报错）
person.get("age")       # 25（安全访问）
person.get("city", "Unknown")  # 不存在返回默认值

# 遍历
for key, value in person.items():
    print(f"{key}: {value}")
```

### 查找表模式（替代 if-elif）

**原始代码（s03_todo_write.py 第 85 行）：**

```python
marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
lines.append(f"{marker} #{item['id']}: {item['text']}")
```

#### 写法对比

```python
# 方式 1：字典查找（简洁）
status_map = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
marker = status_map[item["status"]]

# 方式 2：if-elif-else（冗长）
if item["status"] == "pending":
    marker = "[ ]"
elif item["status"] == "in_progress":
    marker = "[>]"
elif item["status"] == "completed":
    marker = "[x]"
```

| 写法 | 优点 | 适用场景 |
|------|------|----------|
| 字典查找 | 简洁、扩展性好 | 简单的键值映射 |
| if-elif | 可执行复杂逻辑 | 需要条件判断 |

---

## 九、lambda 函数与参数解包

### lambda 匿名函数

```python
# 基本语法：lambda 参数: 返回值
add = lambda x, y: x + y
print(add(2, 3))  # 5

# 无参数
greet = lambda: "Hello!"
print(greet())  # Hello!
```

### *args 和 **kw 参数

```python
# *args：接收任意多个位置参数，打包成元组
def show_args(*args):
    print(f"args = {args}")

show_args(1, 2, 3)  # args = (1, 2, 3)

# **kw：接收任意多个关键字参数，打包成字典
def show_kwargs(**kw):
    print(f"kw = {kw}")

show_kwargs(name="Alice", age=25)  # kw = {'name': 'Alice', 'age': 25}
```

### 实际应用：工具分发映射表

**原始代码（s03_todo_write.py 第 144-150 行）：**

```python
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo":       lambda **kw: TODO.update(kw["items"]),
}
```

### 调用过程解析

```python
# 1. LLM 返回的工具调用
tool_name = "bash"
arguments = {"command": "ls -la"}

# 2. 从映射表获取 handler
handler = TOOL_HANDLERS[tool_name]
# handler = lambda **kw: run_bash(kw["command"])

# 3. 用 ** 解包字典为关键字参数
result = handler(**arguments)
# 等价于：handler(command="ls -la")
# 内部：kw = {"command": "ls -la"}
#       run_bash(kw["command"]) → run_bash("ls -la")
```

### kw.get() vs kw["key"]

```python
# 直接访问：key 不存在会报错
limit = kw["limit"]  # KeyError if not exists

# 安全访问：可设默认值
limit = kw.get("limit")        # 不存在返回 None
limit = kw.get("limit", 100)   # 不存在返回 100
```

---

## 十、类与面向对象

### 类的定义（s03_todo_write.py 第 56 行）

```python
class TodoManager:
    def __init__(self):
        self.items = []  # 实例属性

    def update(self, items: list) -> str:
        self.items = items
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        return "\n".join([...])
```

### 与 Java 对比

| Python | Java |
|--------|------|
| `class MyClass:` | `public class MyClass {}` |
| `def __init__(self):` | `public MyClass() {}` |
| `self.attr` | `this.attr` |
| `self.method()` | `this.method()` |
| 不需要声明属性类型 | 需要声明属性类型 |
| 没有访问修饰符 | `public/private/protected` |

### 构造方法 __init__

```python
class Person:
    def __init__(self, name: str, age: int = 18):  # 默认参数
        self.name = name       # 创建实例属性
        self.age = age

# 创建实例
p = Person("Alice")         # age 使用默认值 18
p2 = Person("Bob", 25)      # age 是 25
```

### 真值判断（Truthy/Falsy）

```python
# Python 中以下值视为 False
if not []:      # 空列表
if not {}:      # 空字典
if not "":      # 空字符串
if not 0:       # 数字零
if not None:    # None

# 所以可以这样写（更 Pythonic）
if not self.items:
    return "No todos."
```

---

## 十一、列表推导式与生成器

### 列表推导式

```python
# 基础语法：[表达式 for 变量 in 可迭代对象]

# 示例 1：平方数
squares = [x**2 for x in range(5)]  # [0, 1, 4, 9, 16]

# 示例 2：带条件
even_squares = [x**2 for x in range(10) if x % 2 == 0]  # [0, 4, 16, 36, 64]

# 示例 3：字典列表
users = [{"id": u.id, "name": u.name} for u in user_list]
```

### enumerate() 函数

```python
fruits = ["apple", "banana", "cherry"]

for i, fruit in enumerate(fruits, start=1):
    print(f"{i}: {fruit}")

# 输出：
# 1: apple
# 2: banana
# 3: cherry
```

### sum() + 生成器表达式

```python
# 计数完成的任务
done = sum(1 for t in self.items if t["status"] == "completed")

# 等价于
done = 0
for t in self.items:
    if t["status"] == "completed":
        done += 1
```

### 与 Java Stream 对比

```python
# Python
squares = [x**2 for x in range(5) if x % 2 == 0]

# Java
List<Integer> squares = IntStream.range(0, 5)
    .filter(x -> x % 2 == 0)
    .map(x -> x * x)
    .boxed()
    .collect(Collectors.toList());
```

---

## 十二、TodoManager 任务管理

### 完整实现（s03_todo_write.py 第 56-89 行）

```python
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
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

    def render(self) -> str:
        if not self.items:
            return "No todos."

        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")

        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)
```

### 数据验证规则

| 验证项 | 规则 |
|--------|------|
| 任务数量 | 最多 20 个 |
| text | 必须存在，不能为空 |
| status | 只能是 pending/in_progress/completed |
| in_progress | 同时只能有 1 个 |

### 任务状态流转

```
[ ] pending    →  开始任务  →  [>] in_progress  →  完成  →  [x] completed
                     ↑
                     └───────── 可随时更新进度
```

---

## 十三、工具分发系统

### 完整工具定义（s02_tool_use.py 第 135-194 行）

```python
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
    # ... write_file, edit_file, todo
]
```

### Anthropic vs OpenAI/Qwen 格式对比

| 特性 | Anthropic | OpenAI/Qwen（本代码） |
|------|-----------|----------------------|
| 工具定义 | `{name, input_schema}` | `{type: "function", function: {...}}` |
| API 调用 | `messages.create()` | `chat.completions.create()` |
| system 参数 | 单独参数 | 放入 messages 列表 |
| 响应解析 | `response.content[]` | `response.choices[0].message.tool_calls[]` |
| 工具结果 | `{type: "tool_result"}` | `{role: "tool"}` |

### 核心 Agent 循环

```python
def agent_loop(messages: list):
    while True:
        # 1. 调用 LLM
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=8000,
        )

        # 2. 检查是否需要工具调用
        if response.choices[0].finish_reason != "tool_calls":
            return  # 模型不再调用工具，结束

        # 3. 执行工具
        results = []
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            handler = TOOL_HANDLERS.get(name)

            if handler:
                output = handler(**arguments)
            else:
                output = f"Unknown tool: {name}"

            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": output
            })

        # 4. 继续循环
        messages.append({"role": "assistant", "content": message.content})
        messages.extend(results)
```

### 流程图

```
┌─────────────────────────────────────────────────┐
│                   Agent Loop                     │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│            调用 LLM API (chat.completions)       │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────────┐
         │ finish_reason ==        │
         │ "tool_calls"?            │
         └───────────┬───────────────┘
              Yes    │    No
               ▼              │
    ┌──────────────────┐       │
    │ 遍历 tool_calls  │       │
    │ 解析 arguments   │       │
    │ 调用 handler()    │       │
    └────────┬─────────┘       │
             │                 │
             ▼                 │
    ┌──────────────────┐       │
    │ 收集结果到 msgs  │       │
    └────────┬─────────┘       │
             │                 │
             └──────► (循环) ──┘
                           │
                           ▼
                    ┌──────────────┐
                    │    结束      │
                    └──────────────┘
```

---

## 总结：Python 核心知识点一览

| 知识点 | 代码体现 | 重要性 |
|--------|----------|--------|
| f-string | `f"{var}"` | ⭐⭐⭐ |
| 类型注解 | `def func(x: int) -> str` | ⭐⭐⭐ |
| pathlib | `Path.cwd()`, `p.read_text()` | ⭐⭐⭐ |
| 字典查找表 | `{status: marker}[key]` | ⭐⭐⭐ |
| lambda | `lambda **kw: func(kw["x"])` | ⭐⭐ |
| **kw 解包 | `handler(**arguments)` | ⭐⭐⭐ |
| 列表推导式 | `[x for x in items]` | ⭐⭐⭐ |
| enumerate | `for i, item in enumerate()` | ⭐⭐ |
| 类定义 | `class TodoManager:` | ⭐⭐⭐ |
| try/except | 异常处理 | ⭐⭐⭐ |
| 生成器表达式 | `sum(1 for t in items if ...)` | ⭐⭐ |

---

## 下一步学习

- [s04-subagent.md](s04-subagent.md) - 子代理系统
- [s05-skill-loading.md](s05-skill-loading.md) - 技能加载机制
- [s06-context-compact.md](s06-context-compact.md) - 上下文压缩
