#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""

这个文件tools里面的search-api是我让程序自己加上去的。可以对输入的语句进行网页搜索返回结果。“
我们选用的是 博查搜索(https://open.bochaai.com/) 提供的api，你要去注册一个博查的  api  key，填写到.env
"""

import os
import sys
from openai import OpenAI
from dotenv import load_dotenv
import json
import subprocess

# ── Windows GBK 终端编码兼容 ──────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() in ('gbk', 'gb2312', 'cp936'):
    sys.stdout.reconfigure(errors='replace')

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
    # ── 新增: 类似 Claude Code 的 grep 工具 ─────────────────────────
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search files for a pattern using ripgrep (rg) or fallback to grep. Returns matching lines with file paths and line numbers. Supports regex patterns. Useful for finding where code is defined, searching for references, or exploring codebases.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The search pattern (regex supported). eg: 'def run_' or 'import os' or 'class.*Handler'"
                    },
                    "path": {
                        "type": "string",
                        "description": "The directory or file to search in. Default is current working directory.",
                        "default": "."
                    },
                    "include": {
                        "type": "string",
                        "description": "File glob pattern to include (e.g. '*.py', '*.{py,js,ts}'). Only search matching files."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 50).",
                        "default": 50
                    }
                },
                "required": ["pattern"]
            },
        }
    },
    # ── 新增: 类似 Claude Code 的 webfetch 工具 ────────────────────
    {
        "type": "function",
        "function": {
            "name": "webfetch",
            "description": "Fetch and retrieve the content of a webpage at a given URL. Useful for reading documentation, getting live data from web pages, or checking web APIs. Returns the page content as text (up to 50000 characters).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to fetch, including protocol (http:// or https://)"
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum number of characters to return (default 50000). Use smaller values for speed.",
                        "default": 50000
                    }
                },
                "required": ["url"]
            },
        }
    },
    # ── 新增: search_api 工具 ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "search_api",
            "description": "对输入的语句进行网页搜索，返回结构化的搜索结果（含标题、来源、链接、日期、摘要等）。底层使用 Bocha AI 搜索引擎。适合需要实时信息、最新新闻、知识查询等场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，支持自然语言查询，返回结构化的搜索结果（含标题、来源、链接、日期、摘要等"
                    },
                    "count": {
                        "type": "integer",
                        "description": "返回结果数量，默认10，最大20",
                        "default": 10
                    }
                },
                "required": ["query"]
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


# ── 新增: 类似 Claude Code 的 grep 工具实现 ──────────────────────
def grep_files(pattern: str, path: str = ".", include: str = "", max_results: int = 50) -> str:
    """
    Search files for a pattern using ripgrep (rg) or fallback to grep.
    """
    # 先尝试用 rg (ripgrep)，没有则 fallback 到 grep
    cmd_parts = []
    
    # 检查 rg 是否可用
    try:
        subprocess.run(["rg", "--version"], capture_output=True, text=True, timeout=5)
        cmd_parts = ["rg", "-n"]
        if include:
            cmd_parts.extend(["-g", include])
        cmd_parts.extend([pattern, path])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # fallback 到 grep
        cmd_parts = ["grep", "-rn"]
        if include:
            # grep 的 include 语法不同
            # 把 *.py 转成 --include=*.py
            for ext in include.split(","):
                ext = ext.strip()
                if ext:
                    cmd_parts.append(f"--include={ext}")
        cmd_parts.extend([pattern, path])
    
    try:
        r = subprocess.run(cmd_parts, capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            lines = (r.stdout or "").strip().split('\n')
            # 限制返回行数
            limited = lines[:max_results]
            result = '\n'.join(limited)
            total = len(lines)
            extra = ""
            if total > max_results:
                extra = f"\n... and {total - max_results} more matches (use max_results to see more)"
            return f"Found {total} match(es):\n{result}{extra}"
        elif r.returncode == 1:
            return f"No matches found for pattern: {pattern}"
        else:
            stderr = (r.stderr or "").strip()
            return f"Error searching (exit code {r.returncode}): {stderr[:2000]}"
    except subprocess.TimeoutExpired:
        return "Error: grep search timed out (30s)"
    except FileNotFoundError:
        return "Error: Neither 'rg' (ripgrep) nor 'grep' found on system."
    except Exception as e:
        return f"Error during grep: {e}"


# ── 新增: 类似 Claude Code 的 webfetch 工具实现 ────────────────
import requests
import importlib.util

# ── 动态导入 search-api.py（文件名含横线，需用 importlib） ─────
_search_api_module = None
def _get_search_api():
    global _search_api_module
    if _search_api_module is not None:
        return _search_api_module
    search_api_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search-api.py")
    if not os.path.exists(search_api_path):
        # 也尝试当前目录
        search_api_path = os.path.join(os.getcwd(), "search-api.py")
    if not os.path.exists(search_api_path):
        return None
    spec = importlib.util.spec_from_file_location("search_api", search_api_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _search_api_module = mod
    return mod

def search_api(query: str, count: int = 10) -> str:
    """
    对输入的语句进行网页搜索，返回结构化的搜索结果。
    底层调用 search-api.py 中的 search() 函数 (Bocha AI 搜索 API)。
    """
    mod = _get_search_api()
    if mod is None:
        return "错误: 找不到 search-api.py 文件"
    try:
        return mod.search(query, count=count)
    except Exception as e:
        return f"搜索出错: {str(e)[:500]}"

def webfetch(url: str, max_length: int = 50000) -> str:
    """
    Fetch the content of a webpage at the given URL.
    Returns the text content (up to max_length characters).
    """
    # 安全检查：只允许 http/https 协议
    if not url.startswith(("http://", "https://")):
        return f"Error: Only http:// and https:// URLs are supported. Got: {url[:50]}"
    
    # 阻止内网/本地地址（安全防护）
    blocked_prefixes = [
        "http://localhost", "https://localhost",
        "http://127.", "https://127.",
        "http://10.", "https://10.",
        "http://172.16.", "https://172.16.",
        "http://192.168.", "https://192.168.",
        "http://0.0.0.0", "https://0.0.0.0",
        "http://[::1]", "https://[::1]",
    ]
    for prefix in blocked_prefixes:
        if url.lower().startswith(prefix):
            return f"Error: Blocked internal/private network address: {url[:60]}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        r.raise_for_status()

        # 尝试从响应头或 HTML 中获取编码
        content_type = r.headers.get("content-type", "")
        r.encoding = r.apparent_encoding or r.encoding or "utf-8"

        text = r.text

        # 简单清理：移除 HTML 标签？不，让模型自己处理原始文本
        # 但可以截断到 max_length
        if len(text) > max_length:
            text = text[:max_length] + f"\n... (truncated, full length was {len(text)} chars)"

        return text
    except requests.exceptions.Timeout:
        return f"Error: Request timed out after 30 seconds for URL: {url}"
    except requests.exceptions.ConnectionError as e:
        return f"Error: Connection failed for URL: {url}\nDetails: {str(e)[:500]}"
    except requests.exceptions.HTTPError as e:
        return f"Error: HTTP {e.response.status_code} for URL: {url}"
    except Exception as e:
        return f"Error fetching URL {url}: {str(e)[:1000]}"


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
                # ── 新增: 处理 grep 工具调用 ─────────────────────
                elif tc.function.name == "grep":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33mSearching for: {args['pattern']}...\033[0m")
                    output = grep_files(
                        args["pattern"],
                        args.get("path", "."),
                        args.get("include", ""),
                        args.get("max_results", 50),
                    )
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                # ── 新增: 处理 webfetch 工具调用 ─────────────────
                elif tc.function.name == "webfetch":
                    args = json.loads(tc.function.arguments)
                    url = args["url"]
                    max_length = args.get("max_length", 50000)
                    print(f"\033[33mFetching: {url}...\033[0m")
                    output = webfetch(url, max_length)
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                # ── 新增: 处理 search_api 工具调用 ──────────────
                elif tc.function.name == "search_api":
                    args = json.loads(tc.function.arguments)
                    query = args["query"]
                    count = args.get("count", 10)
                    print(f"\033[33mSearching: {query}...\033[0m")
                    output = search_api(query, count)
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
    history = [{"role": "system", "content": "你是一个有帮助的助手，当你修改完代码后，请用 bash 工具运行 python 文件名.py 来验证修改是否成功，如果出错则修复"}]
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
