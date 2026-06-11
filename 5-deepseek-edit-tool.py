#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""

添加了  edit 功能，可以修改文件。
"""

import os
from openai import OpenAI
from dotenv import load_dotenv
import json
import subprocess

load_dotenv(override=True)

# ── 配置 ────────────────────────────────────────────
# 环境变量 DEEPSEEK_API_KEY 在 .env 或系统中设置
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
)
MODEL = "deepseek-v4-flash"



TOOLS = [{
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    }
},
    {
        "type": "function",
        "function": {
            "name": "weather",
            "description": "Get the current weather for a location.",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file at the given path. Returns the file content as text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Absolute or relative path to the file to read"
                    }
                },
                "required": ["filepath"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write"
                    }
                },
                "required": ["filepath", "content"],
            },
        }
    },
    # ── 新增: 类似 Claude Code 的 edit 工具 ─────────────────────────
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Edit a file by finding and replacing text. Like Claude Code's edit tool. Uses old_string to locate the text to replace, then replaces it with new_string. This is a surgical find-and-replace operation — use unique context around the target to avoid mismatches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "The absolute or relative path to the file to edit"
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact text in the file to find and replace. Must be unique enough to locate precisely. Include surrounding context for uniqueness."
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The new text to replace old_string with."
                    }
                },
                "required": ["filepath", "old_string", "new_string"],
            },
        }
    },
]

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    
def get_weather(location: str) -> str:
    # 这里直接返回一个固定的字符串，实际应用中可以调用天气API获取实时数据
    return f"The current weather in {location} is sunny with a temperature of 25°C."
def read_file(filepath: str) -> str:
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return content[:50000] if content else '(empty file)'
    except FileNotFoundError:
        return f'Error: File not found: {filepath}'
    except IsADirectoryError:
        return f'Error: Path is a directory, not a file: {filepath}'
    except PermissionError:
        return f'Error: Permission denied: {filepath}'
    except Exception as e:
        return f'Error reading file {filepath}: {e}'

def write_file(filepath: str, content: str) -> str:
    """Write content to a file."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {filepath}"
    except PermissionError:
        return f"Error: Permission denied: {filepath}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {filepath}"
    except Exception as e:
        return f"Error writing file {filepath}: {e}"

# ── 新增: 类似 Claude Code 的 edit 工具实现 ──────────────────────
def edit_file(filepath: str, old_string: str, new_string: str) -> str:
    """
    Edit a file by finding and replacing text.
    Like Claude Code's edit tool — surgical find-and-replace.
    
    Parameters:
        filepath: Path to the file
        old_string: The exact text to find (must exist exactly once, or with unique context)
        new_string: The replacement text
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except FileNotFoundError:
        return f'Error: File not found: {filepath}'
    except IsADirectoryError:
        return f'Error: Path is a directory, not a file: {filepath}'
    except PermissionError:
        return f'Error: Permission denied: {filepath}'
    except Exception as e:
        return f'Error reading file {filepath}: {e}'

    # 检查 old_string 是否存在于文件中
    if old_string not in content:
        return (
            f'Error: The `old_string` was not found in file "{filepath}".\n'
            f'Make sure you include enough unique surrounding context to locate it precisely.\n'
            f'Tip: use read_file first to see exact content.'
        )

    # 统计出现次数
    count = content.count(old_string)
    if count > 1:
        return (
            f'Error: Found {count} occurrences of old_string in "{filepath}".\n'
            f'Please use more unique surrounding context so the match is unambiguous.'
        )

    # 执行替换
    new_content = content.replace(old_string, new_string, 1)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
    except PermissionError:
        return f'Error: Permission denied writing to {filepath}'
    except Exception as e:
        return f'Error writing file {filepath}: {e}'

    # 返回差异摘要
    old_lines = old_string.split('\n')
    new_lines = new_string.split('\n')
    return (
        f'Successfully edited file "{filepath}".\n'
        f'Replaced {len(old_lines)} line(s) with {len(new_lines)} line(s).\n'
        f'Changes applied to the file on disk.'
    )


# ── 工具调用循环 ────────────────────────────────────
def chat(messages: list):
    """发送对话历史，循环处理大模型发过来的工具调用，直到模型返回纯文本。"""
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_completion_tokens=1024,
            temperature=0.7,
            tools=TOOLS,
            tool_choice="auto",
            timeout=120.0,
        )
        msg = response.choices[0].message

        # 模型要调工具 → 执行并回传结果
        if msg.tool_calls:
            # 先把 assistant 这轮（含 tool_calls）记入历史
            assistant_msg = {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
            # DeepSeek thinking 模式要求 reasoning_content 必须传回
            if msg.reasoning_content:
                assistant_msg["reasoning_content"] = msg.reasoning_content
            messages.append(assistant_msg)

            for tc in msg.tool_calls:
                if tc.function.name == "bash":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m$ {args['command']}\033[0m")
                    output = run_bash(args["command"])
                    print(output[:200])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "weather":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33mGetting weather for {args['location']}...\033[0m")
                    output = get_weather(args["location"])
                    print(output)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "read_file":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33mReading file: {args['filepath']}...\033[0m")
                    output = read_file(args["filepath"])
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "write_file":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33mWriting file: {args['filepath']}...\033[0m")
                    output = write_file(args["filepath"], args["content"])
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                # ── 新增: 处理 edit 工具调用 ─────────────────────
                elif tc.function.name == "edit":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33mEditing file: {args['filepath']}...\033[0m")
                    output = edit_file(args["filepath"], args["old_string"], args["new_string"])
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
            # 继续循环，让模型看工具结果
            continue
        # 测试语句
        print('测试语句，到此工具调用已经结束了')
        # 模型返回纯文本 → 记入历史并结束
        final_msg = {"role": "assistant", "content": msg.content}
        if msg.reasoning_content:
            final_msg["reasoning_content"] = msg.reasoning_content
        messages.append(final_msg)
        return


if __name__ == "__main__":
    history = [{"role": "system", "content": "你是一个有帮助的助手"}]
    print("输入对话内容，q/exit 退出\n")
    while True:
        
        try:
            query = input("\033[36mYou >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            exit(0)
        if query.strip().lower() in ("q", "exit", ""):
            exit(0)
        history.append({"role": "user", "content": query})
        chat(history)
        print(history[-1]["content"])
