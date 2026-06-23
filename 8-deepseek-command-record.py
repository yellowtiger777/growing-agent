
#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""
每次会把输入的语句，存储到command-test.txt文件里面，方便以后采用这些测试语句。

"""

import os
import sys
import datetime
from openai import OpenAI
from dotenv import load_dotenv
import json
import subprocess
import requests
import importlib.util

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
    # ── 新增: project_lookup 工具 ────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "project_lookup",
            "description": "当用户提到正在做某个项目时，在项目管理.md中查找该项目的相关信息（如项目描述、技术栈、目标、进度等）。用于快速回顾项目背景信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "要查找的项目名称，如 '智能客服系统'、'数据中台' 等。会模糊匹配项目管理.md中的项目标题和内容。"
                    }
                },
                "required": ["project_name"]
            },
        }
    },
]

def run_bash(command: str) -> str:
    # 增强的危险命令过滤（支持空格/大小写绕过检测）
    import re
    dangerous_patterns = [
        r'\brm\s+-rf\s+/',           # rm -rf / (任意变体)
        r'\bshutdown\b',               # shutdown
        r'\breboot\b',                 # reboot
        r'\bhalt\b',                   # halt
        r'\bpoweroff\b',               # poweroff
        r'\bformat\s+[c-z]\s*:',      # format C: / D:
        r'>\s*/dev/',                   # > /dev/ (危险重定向)
        r':\(\)\s*\{|:\\\(\)\s*\{',  # fork bomb
        r'\bdd\s+if=',                 # dd if= (直接写磁盘)
        r'mkfs\.',                      # mkfs.* (格式化文件系统)
        r'\bwget\s+.*\|\s*bash\b',  # wget xxx | bash
        r'\bcurl\s+.*\|\s*bash\b',  # curl xxx | bash
    ]
    for p in dangerous_patterns:
        if re.search(p, command, re.IGNORECASE):
            return f"Error: Dangerous command blocked (matched pattern: {p})"
    # 白名单：允许常见的 sudo 用法（apt install, systemctl, npm install 等）
    allowed_sudo = ['apt', 'apt-get', 'npm', 'pip', 'pip3', 'cargo', 'systemctl', 'service', 'mkdir', 'cp', 'mv', 'chmod', 'chown']
    # 单独检查 sudo - 允许白名单命令带 sudo
    if re.search(r'\bsudo\b', command):
        # 提取 sudo 后的第一个词
        m = re.search(r'\bsudo\s+([a-zA-Z0-9_\-]+)', command)
        if m and m.group(1) not in allowed_sudo:
            return f"Error: 'sudo {m.group(1)}' is not in the allowed sudo commands whitelist"

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

# ── 新增: project_lookup 工具实现 ──────────────────────────
def project_lookup(project_name: str) -> str:
    """
    在项目管理.md中查找指定项目的相关信息。
    读取与脚本同目录下的项目管理.md文件，按项目名称进行模糊匹配，
    返回匹配到的项目信息（标题、描述、技术栈、目标、进度等）。
    """
    # 项目管理.md 与脚本同目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    md_path = os.path.join(script_dir, "项目管理.md")

    if not os.path.exists(md_path):
        return f"未找到项目管理.md文件（路径: {md_path}），请先创建该文件并录入项目信息。"

    try:
        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"读取项目管理.md失败: {e}"

    if not content.strip():
        return "项目管理.md文件为空，请先录入项目信息。"

    # 将内容按行分割，方便处理
    lines = content.split("\n")
    
    # 找到所有项目标题（以 ## 开头或 **项目名** 等形式）
    # 策略：按 Markdown 标题（## 或 ###）分段，找到包含项目名称的段落
    sections = []
    current_section = []
    current_title = ""

    for line in lines:
        # 检测 Markdown 标题（## 或 ###）
        stripped = line.strip()
        if stripped.startswith("##") or stripped.startswith("===") or stripped.startswith("---"):
            # 保存上一段
            if current_section:
                sections.append((current_title, "\n".join(current_section)))
            current_section = []
            current_title = stripped.lstrip("#=-").strip()
        else:
            current_section.append(line)
    # 最后一段
    if current_section:
        sections.append((current_title, "\n".join(current_section)))

    # 如果没有分段的标题，说明可能是列表/段落格式，直接用全文搜索
    if not sections or all(not title for title, _ in sections):
        # 整篇当成一个大段
        sections = [("", content)]

    # 模糊匹配项目名称（忽略大小写，匹配包含关系）
    project_lower = project_name.lower().strip()
    
    matched_results = []
    for title, body in sections:
        # 在标题和正文中搜索
        combined = title + "\n" + body
        combined_lower = combined.lower()
        
        if project_lower in combined_lower:
            # 提取这一段内容（限制长度避免返回太多）
            snippet = f"【{title or '无标题'}】\n{body.strip()[:2000]}"
            if len(body.strip()) > 2000:
                snippet += "\n... (内容较长，已截取前2000字符)"
            matched_results.append(snippet)

    if matched_results:
        result = f"在项目管理.md中找到与「{project_name}」相关的项目信息（共 {len(matched_results)} 条匹配）：\n\n"
        result += "\n\n---\n\n".join(matched_results)
        return result[:10000]  # 限制总输出长度
    else:
        # 没找到精确匹配，列出所有项目供参考
        all_titles = []
        for title, body in sections:
            if title:
                all_titles.append(f"  - {title}")
        title_hint = ""
        if all_titles:
            title_hint = "\n当前项目管理.md中记录的项目有：\n" + "\n".join(all_titles[:30])
        
        return (
            f"在项目管理.md中未找到与「{project_name}」匹配的项目信息。"
            f"{title_hint}\n\n"
            f"提示：请确认项目名称是否正确，或先在项目管理.md中录入该项目的信息。"
        )


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
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=4096,
                temperature=0.7,
                tools=TOOLS,
                tool_choice="auto",
                timeout=120.0,
            )
            msg = response.choices[0].message
        except Exception as e:
            err_msg = f"API调用失败: {str(e)[:500]}"
            print(f"\033[31m{err_msg}\033[0m")
            messages.append({"role": "assistant", "content": f"错误: {err_msg}"})
            return

        # 模型要调工具 → 执行并回传结果
        if msg.tool_calls:
            # 先把 assistant 这轮（含 tool_calls）记入历史
            assistant_msg = {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
            # DeepSeek thinking 模式要求 reasoning_content 必须传回
            reasoning = getattr(msg, 'reasoning_content', None)
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
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
                # ── 新增: 处理 project_lookup 工具调用 ──────────
                elif tc.function.name == "project_lookup":
                    args = json.loads(tc.function.arguments)
                    project_name = args["project_name"]
                    print(f"\033[33m🔍 在项目管理.md中查找项目: {project_name}...\033[0m")
                    output = project_lookup(project_name)
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
        reasoning = getattr(msg, 'reasoning_content', None)
        if reasoning:
            final_msg["reasoning_content"] = reasoning
        messages.append(final_msg)
        return


if __name__ == "__main__":
    # ── 获取当前脚本的绝对路径 ──────────────────────────
    script_path = os.path.abspath(__file__)
    print(f"\033[32m📄 当前 Agent 代码文件: {script_path}\033[0m")

    # ── 启动时自动读取经验记录 + 用户偏好 ──────────────────
    def _load_md(filename: str, label: str) -> str:
        path = os.path.join(os.getcwd(), filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                print(f"\033[32m📖 已加载 {label} ({len(content)} 字符)\033[0m")
                return content
            except Exception as e:
                print(f"\033[31m⚠️  读取 {filename} 失败: {e}\033[0m")
        else:
            print(f"\033[33m⚠️  未找到 {filename}\033[0m")
        return ""

    experience_content = _load_md("经验记录.md", "经验记录")
    user_content = _load_md("user.md", "用户偏好")

    system_prompt = "你是一个有帮助的助手，当你修改完代码后，请用 bash 工具运行 python 文件名.py 来验证修改是否成功，如果出错则修复"
    system_prompt += "\n\n【核心规则】每一次有失败的操作（工具调用报错、测试不通过、抓取失败、路径错误等），都必须分析原因，将经验教训总结写入 经验记录.md，格式参照已有条目。这非常重要，请严格遵守。"
    # 告诉大模型当前运行的 Agent 代码文件路径
    system_prompt += f"\n\n你正在运行的 agent 代码文件路径是: {script_path}"

    snippets = []
    if experience_content:
        snippets.append(
            "以下是你过往的经验教训记录，请仔细阅读并避免重复犯错：\n"
            f"{experience_content}"
        )
    if user_content:
        snippets.append(
            "以下是用户的做事方法与偏好，请遵循：\n"
            f"{user_content}"
        )
    if snippets:
        system_prompt += "\n\n---\n" + "\n\n---\n".join(snippets)
    history = [{"role": "system", "content": system_prompt}]
    print("输入对话内容，q/exit 退出\n")
    # ── 命令记录文件路径（command-test.txt 与脚本同目录） ─────
    command_log_path = os.path.join(os.path.dirname(script_path), "command-test.txt")

    # ── 多行输入模式：空行发送，支持粘贴多行文本 ──────────
    print("\033[33m💡 多行输入：逐行输入，空行（直接回车）发送内容；输入 q 或 exit 退出\033[0m")
    while True:
        lines = []
        while True:
            try:
                line = input('you>>>')
            except (EOFError, KeyboardInterrupt):
                exit(0)
            # 检测退出命令
            if line.strip().lower() in ("q", "exit"):
                exit(0)
            # 空行触发发送
            if line == '':
                break
            lines.append(line)

        query = '\n'.join(lines)
        if not query.strip():
            continue

        # ── 记录用户输入到 command-test.txt（JSON Lines 格式） ─
        log_record = {
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "program": script_path,
            "input": query,
        }
        try:
            with open(command_log_path, "a", encoding="utf-8") as log_f:
                log_f.write(json.dumps(log_record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"\033[31m⚠️  写入命令记录失败: {e}\033[0m")

        history.append({"role": "user", "content": query})
        # 上下文窗口管理：超过 80 条消息时丢弃最早的非 system 消息
        MAX_HISTORY = 80
        non_system = [m for m in history if m["role"] != "system"]
        if len(non_system) > MAX_HISTORY:
            # 保留 system prompt，丢弃最早的用户/助手消息
            system_msgs = [m for m in history if m["role"] == "system"]
            user_assistant_msgs = [m for m in history if m["role"] != "system"]
            # 丢弃最旧的 20 条
            user_assistant_msgs = user_assistant_msgs[20:]
            history = system_msgs + user_assistant_msgs
            print(f"\033[33m🧹 上下文已清理: 保留 {len(history)} 条消息 ({len(system_msgs)} system + {len(user_assistant_msgs)} 对话)\033[0m")
        chat(history)
        print(history[-1]["content"])
