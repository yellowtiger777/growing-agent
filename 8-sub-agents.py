
#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""
和c7-agents相比，现在这个是真正的异步执行，子agent在干活的同时，用户仍然可以对主线程输入

核心特性：
1. 异步架构：主线程输入永不阻塞，Lead 在后台线程处理
2. 多 Agent 独立工作：队友线程各自独立运行，互不干扰
3. @name 直接对话：用 @队友名 消息 直接与任意 Agent 交互
4. Lead 负责分配任务、审阅交付物、协调团队
5. 每个 Agent 都有独立的输入队列，用户可随时切换对话目标
"""

import os
import sys
import datetime
import json
import subprocess
import threading
import time
import locale
import httpx
import requests
import uuid
import queue
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from http.server import HTTPServer, BaseHTTPRequestHandler




# ── Windows GBK 终端编码兼容 ──────────────────────────
# 不管 stdin/stdout 是什么编码，都设置 errors='replace' 防止管道重定向时解码崩溃
try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass
try:
    sys.stdin.reconfigure(errors='replace')
except Exception:
    pass

load_dotenv(override=True)

# ── 配置 ────────────────────────────────────────────
# 环境变量 DEEPSEEK_API_KEY 在 .env 或系统中设置
# 使用无代理的 httpx 客户端，确保 DeepSeek API 始终直连（避免代理导致的请求异常）
_direct_http_client = httpx.Client(proxies=None, trust_env=False, verify=True)
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    http_client=_direct_http_client,
)
MODEL = "deepseek-v4-flash"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
SYS_ENCODING = locale.getpreferredencoding() or "gbk"  # Windows 中文系统 GBK，避免命令输出乱码
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # 模块级脚本目录



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
    # ── Agent Teams 工具 ─────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "spawn_teammate",
            "description": "Spawn a persistent teammate (agent) that runs in its own thread. The teammate will work on tasks independently and report back when done. Use this to delegate work. NEW WORKFLOW: After a teammate is approved, use delete_teammate to remove them, then spawn a new one with the SAME name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Teammate's name. If a previous teammate was deleted, you can reuse the same name."},
                    "role": {"type": "string", "description": "Teammate's role (e.g., 'coder', 'reviewer', 'tester', 'writer')"},
                    "prompt": {"type": "string", "description": "Initial task description and instructions"}
                },
                "required": ["name", "role", "prompt"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_teammates",
            "description": "List all teammates and their current status (working, idle, under_review, etc.)",
            "parameters": {"type": "object", "properties": {}},
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message to a teammate. NOTE: Only message teammates who are currently 'working' or 'under_review'. Do NOT message teammates with 'approved' or deleted status — they have finished/exited. Use spawn_teammate to create new teammates, and delete_teammate to clean up finished ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Teammate's name. Must be a currently active teammate (status: working or under_review), not an approved/completed one."},
                    "content": {"type": "string", "description": "Message content"},
                    "msg_type": {"type": "string", "enum": ["message", "broadcast", "review_request", "review_verdict"], "description": "Message type (default: 'message')"}
                },
                "required": ["to", "content"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_inbox",
            "description": "Read and drain the lead's inbox for messages from teammates.",
            "parameters": {"type": "object", "properties": {}},
        }
    },
    {
        "type": "function",
        "function": {
            "name": "broadcast",
            "description": "Send a message to all teammates at once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Message content to broadcast"}
                },
                "required": ["content"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "review_deliverable",
            "description": "Review a teammate's deliverable FILE for quality by specifying the FILE PATH. Do NOT pass a teammate name — pass an actual file path (e.g. './poem.txt' or '/path/to/file.py'). Use send_message first to ask the teammate what files they created.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the FILE to review (not a teammate name). Must be an actual file path."},
                    "requirements": {"type": "string", "description": "Quality criteria or requirements to check against"}
                },
                "required": ["path"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_redo",
            "description": "Send rework feedback to a teammate. Provide specific, actionable feedback on what needs improvement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "teammate": {"type": "string", "description": "Teammate's name"},
                    "feedback": {"type": "string", "description": "Specific feedback on what to improve"},
                    "task_description": {"type": "string", "description": "Original task description (optional)"}
                },
                "required": ["teammate", "feedback"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "approve_deliverable",
            "description": "Approve a teammate's deliverable and mark their task as complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "teammate": {"type": "string", "description": "Teammate's name"},
                    "feedback": {"type": "string", "description": "Approval feedback or comments"}
                },
                "required": ["teammate"]
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_teammate",
            "description": "Delete a teammate from the team after their work is complete. Cleans up their config, inbox, and thread. Use this AFTER approve_deliverable to remove finished teammates so you can spawn new ones with the same name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "teammate": {"type": "string", "description": "Teammate's name to delete"}
                },
                "required": ["teammate"]
            },
        }
    },
    # GitHub 工具由官方 MCP 服务器动态提供，这里留空占位
]

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, timeout=120)
        # 先试 UTF-8（现代工具/文件内容），失败回退系统编码（dir 等 Windows 命令）
        def _decode(data: bytes) -> str:
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data.decode(SYS_ENCODING, errors="replace")

        out = (_decode(r.stdout or b"") + _decode(r.stderr or b"")).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    
def get_weather(location: str) -> str:
    # 这里直接返回一个固定的字符串，实际应用中可以调用天气API获取实时数据
    return f"The current weather in {location} is sunny with a temperature of 25°C."

# ── HTTP 请求辅助：代理自动回退 ─────────────────────
# 当系统设置了代理但代理软件没运行时，requests 会报 ProxyError。
# 这个函数先尝试用系统代理，如果 ProxyError 则自动回退到直连。
def _request_with_proxy_fallback(method: str, url: str, **kwargs) -> requests.Response:
    """
    发起 HTTP 请求，自动处理代理问题。
    优先使用系统代理（如果代理软件正在运行），
    遇到 ProxyError 则自动回退到直连（绕过系统代理）。
    """
    # 确保有 timeout
    if "timeout" not in kwargs:
        kwargs["timeout"] = 30
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.ProxyError:
        # 代理设置了但不可用 → 回退直连
        kwargs["proxies"] = {"http": "", "https": ""}
        return requests.request(method, url, **kwargs)
    except requests.exceptions.ConnectionError as e:
        # 连接错误也可能是代理导致的，尝试直连
        if "proxy" in str(e).lower() or "connection refused" in str(e).lower():
            kwargs["proxies"] = {"http": "", "https": ""}
            return requests.request(method, url, **kwargs)
        raise


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


# ── GitHub 官方 MCP 客户端 ──────────────────────────
# 启动 github-mcp-server.exe stdio 子进程，通过 MCP 协议调用

mcp_client = None          # MCPClient 实例
MCP_TOOL_NAMES = set()     # 哪些工具名属于 MCP 服务器


class MCPClient:
    """通过 stdio 与 MCP 服务器 (github-mcp-server.exe) 通信。"""

    def __init__(self):
        self.proc = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._stderr = []

    def _read_stderr(self):
        for line in self.proc.stderr:
            self._stderr.append(line.strip())

    def start(self, command: list, env: dict = None):
        env = env or os.environ.copy()
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = GITHUB_TOKEN
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding="utf-8", errors="replace",
        )
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def send(self, method: str, params: dict = None) -> dict:
        with self._lock:
            self._request_id += 1
            req_id = self._request_id
            req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
            self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise ConnectionError("MCP 服务器已关闭 stdout")
                resp = json.loads(line)
                if resp.get("id") == req_id:
                    if "error" in resp:
                        raise RuntimeError(json.dumps(resp["error"], ensure_ascii=False))
                    return resp.get("result", {})

    def notify(self, method: str, params: dict = None):
        with self._lock:
            self.proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "method": method, "params": params or {}},
                ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def initialize(self) -> dict:
        result = self.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "deepseek-agent", "version": "1.0"},
        })
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list:
        return self.send("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具，返回提取后的文本内容。"""
        result = self.send("tools/call", {"name": name, "arguments": arguments})
        # MCP 返回格式: {"content": [{"type": "text", "text": "..."}]}
        content_parts = result.get("content", [])
        texts = []
        for part in content_parts:
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "resource":
                texts.append(part.get("resource", {}).get("text", ""))
        return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)

    def shutdown(self):
        if self.proc:
            self.proc.stdin.close()
            self.proc.terminate()
            time.sleep(0.3)
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc = None


def mcp_tool_to_openai(tool: dict) -> dict:
    """将 MCP tools/list 返回的工具定义转换为 OpenAI/DeepSeek function calling 格式。"""
    schema = tool.get("inputSchema", {"type": "object", "properties": {}})
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": {
                "type": schema.get("type", "object"),
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        },
    }


def init_mcp_server() -> list:
    """启动官方 GitHub MCP 服务器，返回 OpenAI 格式的工具定义列表。"""
    global mcp_client, MCP_TOOL_NAMES

    script_dir = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(script_dir, "github-mcp-official", "github-mcp-server.exe")
    if not os.path.exists(exe):
        print("\033[31mGitHub MCP 服务器未找到，请先运行 18-github-mcp-demo.py 下载\033[0m")
        return []

    if not GITHUB_TOKEN:
        print("\033[33m⚠ GITHUB_TOKEN 未设置，GitHub 工具不可用\033[0m")
        return []

    print(f"\033[32m🐙 启动 GitHub 官方 MCP 服务器...\033[0m")
    mcp_client = MCPClient()
    mcp_client.start([exe, "stdio"])

    try:
        server_info = mcp_client.initialize()
        name = server_info.get("serverInfo", {}).get("name", "?")
        version = server_info.get("serverInfo", {}).get("version", "?")
        print(f"   MCP 服务器: {name} v{version}")

        tools = mcp_client.list_tools()
        MCP_TOOL_NAMES = {t["name"] for t in tools}
        openai_tools = [mcp_tool_to_openai(t) for t in tools]
        print(f"   已加载 \033[33m{len(openai_tools)}\033[0m 个 GitHub 工具\n")
        return openai_tools
    except Exception as e:
        print(f"\033[31mMCP 启动失败: {e}\033[0m")
        mcp_client.shutdown()
        mcp_client = None
        return []


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
        r = _request_with_proxy_fallback("GET", url, headers=headers, allow_redirects=True)
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


# ═══════════════════════════════════════════════════════════
# Agent Teams - 多 Agent 团队协作系统（参考 s09_agent_teams.py）
# ═══════════════════════════════════════════════════════════
"""
多 Agent 团队协作核心机制:
- MessageBus: 基于 JSONL 文件的消息邮箱系统
- TeammateManager: 管理持久化队友线程和状态配置
- spawn_teammate: 启动独立 Agent 线程的工具
- send_message / read_inbox: 队友间通信工具

文件邮箱架构:
.team/
  config.json          # 团队配置（成员名、角色、状态）
  inbox/
    alice.jsonl        # alice 的收件箱（追加写入，读取后清空）
    bob.jsonl          # bob 的收件箱
    lead.jsonl         # 队长的收件箱
"""

# -- Agent Teams 配置 --
VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
    "review_request",
    "review_verdict",
}

STATUS_UNDER_REVIEW = "under_review"
STATUS_REWORKING = "reworking"
STATUS_APPROVED = "approved"
MAX_REDO_ATTEMPTS = 999

TEAM_DIR = Path(SCRIPT_DIR) / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TEAMMATE_LOG = TEAM_DIR / "teammate_output.log"  # 队友后台输出重定向到此文件


def log_teammate(name: str, message: str):
    """将队友的后台输出写入日志文件，避免干扰主线程的输入提示。"""
    try:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with open(TEAMMATE_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{name}] {message}\n")
    except Exception:
        pass  # 日志写入失败不影响核心功能


# -- MessageBus: JSONL inbox per teammate --
class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a", encoding='utf-8') as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []
        messages = []
        for line in inbox_path.read_text(encoding='utf-8').strip().splitlines():
            if line:
                messages.append(json.loads(line))
        inbox_path.write_text("")
        return messages

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


BUS = MessageBus(INBOX_DIR)


# -- TeammateManager: persistent named agents with config.json --
class TeammateManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding='utf-8'))
        return {"team_name": "default", "members": []}

    def _save_config(self):
        self.config_path.write_text(json.dumps(self.config, indent=2), encoding='utf-8')

    def _find_member(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """Spawn a persistent teammate that runs in its own thread."""
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()

        # 创建队友的独立输入队列，使用户可以直接 @name 发送输入
        with teammate_input_lock:
            teammate_input_queues[name] = queue.Queue()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role}) — 可用 @{name} 直接对话"

    def _teammate_loop(self, name: str, role: str, prompt: str):
        """Teammate's agent loop - runs in separate thread."""
        sys_prompt = (
            f"You are '{name}', role: {role}, at {SCRIPT_DIR}. "
            f"Use send_message to communicate. Complete your task. "
            f"After completing your work, you MUST send a review request to 'lead' "
            f"via the send_message tool with msg_type='review_request'. "
            f"If you receive 'REDO:' feedback, follow instructions and redo. "
            f"If you receive 'APPROVED:', your task is done. "
            f"IMPORTANT: If your output/review is long, SAVE IT TO A FILE using write_file, "
            f"then include 'Saved detailed output to FILE: <path>' in your review_request. "
            f"Do NOT rely on the review_request message content for long text - "
            f"the Lead will read the file to see your full output. "
            f"NOTE: The user can send you direct messages via '@{name}' in the main input. "
            f"These will appear as '[DIRECT USER INPUT]' messages. Respond promptly. "
            f"There is a built-in limit of 50 API calls per work round. "
            f"When that limit is reached, the system will automatically ask the Lead "
            f"to evaluate your progress. You don't need to worry about this — just focus on your task."
        )
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()

        def _run_llm_loop(max_iterations=50):
            """
            Run the LLM loop for up to max_iterations.
            Returns:
                True    - Task completed naturally (last response had no tool_calls)
                "hit_max" - Reached max_iterations without completing
                False   - Error occurred
            """
            for i in range(max_iterations):
                # ── 1. 检查队友收件箱（从 Lead 发来的消息） ──
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    messages.append({"role": "user", "content": json.dumps(msg, ensure_ascii=False)})

                # ── 2. 检查用户直接输入队列（主线程 @name 发来的消息） ──
                with teammate_input_lock:
                    dq = teammate_input_queues.get(name)
                if dq:
                    try:
                        while True:
                            direct_user_input = dq.get_nowait()
                            log_teammate(name, f"[来自用户的直接输入] {direct_user_input[:80]}")
                            messages.append({
                                "role": "user",
                                "content": f"[来自用户的直接输入]\n{direct_user_input}",
                            })
                    except queue.Empty:
                        pass
                try:
                    response = client.chat.completions.create(
                        model=MODEL,
                        messages=[{"role": "system", "content": sys_prompt}] + messages,
                        tools=tools,
                        tool_choice="auto",
                        max_tokens=8000,
                    )
                    assistant_msg = response.choices[0].message
                    tool_calls = assistant_msg.tool_calls or []
                    messages.append({
                        "role": "assistant",
                        "content": assistant_msg.content,
                        "tool_calls": tool_calls,
                    })
                    if not tool_calls:
                        return True  # 任务完成（没有工具调用，说明LLM在总结输出）
                    results = []
                    for tc in tool_calls:
                        args = json.loads(tc.function.arguments)
                        output = self._exec(name, tc.function.name, args)
                        log_teammate(name, f"{tc.function.name}: {str(output)[:120]}")
                        results.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(output),
                        })
                    messages.extend(results)
                except Exception as e:
                    log_teammate(name, f"Error: {e}")
                    return False
            return "hit_max"  # 达到次数上限，任务可能还没完成

        # Phase 1: Execute initial task (up to 50 API calls, then check with Lead)
        MAX_API_CALLS_PER_ROUND = 999999
        MAX_TOTAL_API_CALLS = 99999999  # 总上限（实际由用户手动终止）
        
        total_calls = 0
        while total_calls < MAX_TOTAL_API_CALLS:
            result = _run_llm_loop(MAX_API_CALLS_PER_ROUND)
            total_calls += MAX_API_CALLS_PER_ROUND
            
            if result is False:
                # 发生错误
                self._update_status(name, "idle")
                return
            
            if result is True:
                # 任务完成了！进入 Phase 2 提交审查
                self._update_status(name, STATUS_UNDER_REVIEW)
                review_msg = (
                    f"[REVIEW_REQUEST] Teammate '{name}' (role: {role}) completed the task. "
                    f"Please review. If approved, send 'APPROVED: <comments>'. "
                    f"If changes needed, send 'REDO: <specific feedback>'."
                )
                BUS.send(name, "lead", review_msg, "review_request")
                log_teammate(name, "Submitted work for review.")
                break
            
            if result == "hit_max":
                # 达到 50 次 API 调用上限，向 Lead 请求进度评估
                log_teammate(name, f"Reached {total_calls} API calls. Asking Lead for evaluation.")
                
                # 1. 向 Lead 发送评估请求
                eval_msg = (
                    f"[PROGRESS_CHECK] Teammate '{name}' (role: {role}) has used {total_calls} API calls "
                    f"and has NOT finished the task yet. "
                    f"Please evaluate if I am making progress or stuck in a loop.\n"
                    f"Current conversation length: {len(messages)} messages.\n"
                    f"Reply with one of:\n"
                    f"  'CONTINUE: <reason>' — I'm making progress, let me keep working for another round.\n"
                    f"  'SUBMIT: <reason>' — Submit what I have so far for review.\n"
                    f"  'STUCK: <reason>' — I'm in a dead loop, ask the user to decide."
                )
                BUS.send(name, "lead", eval_msg, "message")
                
                # 2. 等待 Lead 回复（最多等60秒，每3秒检查一次）
                lead_verdict = None
                for _ in range(20):  # 20 * 3 = 60 seconds
                    time.sleep(3)
                    inbox = BUS.read_inbox(name)
                    for msg in inbox:
                        content = msg.get("content", "")
                        if "CONTINUE:" in content:
                            lead_verdict = "continue"
                            log_teammate(name, f"Lead says CONTINUE: {content}")
                        elif "SUBMIT:" in content:
                            lead_verdict = "submit"
                            log_teammate(name, f"Lead says SUBMIT: {content}")
                        elif "STUCK:" in content:
                            lead_verdict = "stuck"
                            log_teammate(name, f"Lead says STUCK: {content}")
                        elif content.strip():
                            # 其他消息暂存回收件箱（给下一轮处理）
                            # 重新写入，让下一轮 _run_llm_loop 处理
                            inbox_path = INBOX_DIR / f"{name}.jsonl"
                            with open(inbox_path, "a", encoding='utf-8') as f:
                                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                    if lead_verdict:
                        break
                
                if lead_verdict == "continue":
                    # Lead 认为还在工作，继续下一轮
                    log_teammate(name, "Resuming work for another round.")
                    continue
                elif lead_verdict == "submit":
                    # Lead 认为可以提交当前成果
                    self._update_status(name, STATUS_UNDER_REVIEW)
                    review_msg = (
                        f"[REVIEW_REQUEST] Teammate '{name}' (role: {role}) submitting current work "
                        f"(used {total_calls} API calls, Lead decided to submit). "
                        f"Please review."
                    )
                    BUS.send(name, "lead", review_msg, "review_request")
                    log_teammate(name, "Submitted work (Lead decided to submit early).")
                    break
                elif lead_verdict == "stuck":
                    # Lead 认为可能是死循环，让用户决定
                    log_teammate(name, "Lead thinks it's stuck. Asking user to decide.")
                    # 给 Lead 的收件箱发消息，让 Lead 问用户
                    BUS.send(name, "lead",
                        f"[NEED_USER_DECISION] Teammate '{name}' (role: {role}) has used {total_calls} API calls "
                        f"and Lead thinks it might be stuck in a loop. "
                        f"Please ask the user: should I terminate this teammate or let it continue?",
                        "message")
                    # 等待用户通过 Lead 传达决定（等待 2 分钟）
                    user_decision = None
                    for _ in range(40):  # 40 * 3 = 120 seconds
                        time.sleep(3)
                        inbox = BUS.read_inbox(name)
                        for msg in inbox:
                            content = msg.get("content", "")
                            if "TERMINATE:" in content or "KILL:" in content:
                                user_decision = "terminate"
                                log_teammate(name, f"User says TERMINATE.")
                            elif "CONTINUE:" in content:
                                user_decision = "continue"
                                log_teammate(name, f"User says CONTINUE.")
                            elif content.strip():
                                inbox_path = INBOX_DIR / f"{name}.jsonl"
                                with open(inbox_path, "a", encoding='utf-8') as f:
                                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                        if user_decision:
                            break
                    
                    if user_decision == "terminate":
                        log_teammate(name, "Terminated by user.")
                        self._update_status(name, "idle")
                        return
                    elif user_decision == "continue":
                        log_teammate(name, "User says continue working.")
                        continue
                    else:
                        # 超时未收到决定，默认终止
                        log_teammate(name, "No user decision received within timeout. Defaulting to continue.")
                        # 重新发送提醒给 Lead
                        BUS.send(name, "lead",
                            f"[REMINDER] Teammate '{name}' is still waiting for a decision. "
                            f"Type 'CONTINUE:' or 'TERMINATE:' to decide.",
                            "message")
                        continue
                else:
                    # Lead 没有回复（超时），默认继续
                    log_teammate(name, "No Lead response within timeout. Continuing work.")
                    continue
        
        else:
            # 达到总上限 MAX_TOTAL_API_CALLS
            log_teammate(name, f"Reached total API call limit ({MAX_TOTAL_API_CALLS}). Forcing submission.")
            self._update_status(name, STATUS_UNDER_REVIEW)
            BUS.send(name, "lead",
                f"[REVIEW_REQUEST] Teammate '{name}' (role: {role}) reached total API limit. "
                f"Submitting current work for review.",
                "review_request")

        # Phase 3: Handle feedback (redo cycle) + respond to messages
        for attempt in range(MAX_REDO_ATTEMPTS):
            time.sleep(2)
            inbox = BUS.read_inbox(name)
            verdict_found = False
            has_other_msgs = False
            for msg in inbox:
                content = msg.get("content", "")
                if "REDO:" in content:
                    verdict_found = True
                    log_teammate(name, f"Redo requested (attempt {attempt + 1}/{MAX_REDO_ATTEMPTS})")
                    self._update_status(name, STATUS_REWORKING)
                    messages.append({
                        "role": "user",
                        "content": f"[REDO FEEDBACK]\n{content}\n\nPlease redo based on feedback.",
                    })
                    ok = _run_llm_loop(30)
                    if ok is True:
                        self._update_status(name, STATUS_UNDER_REVIEW)
                        BUS.send(name, "lead", f"[REVIEW_REQUEST] Redone attempt {attempt + 2}.", "review_request")
                    elif ok == "hit_max":
                        # 重做也达到上限，强制提交
                        self._update_status(name, STATUS_UNDER_REVIEW)
                        BUS.send(name, "lead",
                            f"[REVIEW_REQUEST] Redone attempt {attempt + 2} (hit API limit). "
                            f"Submitting current work.",
                            "review_request")
                    else:
                        break
                elif "APPROVED:" in content:
                    verdict_found = True
                    log_teammate(name, "Work APPROVED!")
                    self._update_status(name, STATUS_APPROVED)
                    break
                else:
                    # 普通消息（如 Lead 询问进度、要求展示作品等），需要响应
                    has_other_msgs = True
                    messages.append({
                        "role": "user",
                        "content": f"[MESSAGE from {msg.get('from', 'unknown')}]\n{content}",
                    })
            if has_other_msgs and not verdict_found:
                # 有普通消息需要处理，让 LLM 响应
                _run_llm_loop(30)
            if verdict_found:
                break
            time.sleep(3)

        # Final status
        member = self._find_member(name)
        if member and member["status"] not in ("shutdown", STATUS_APPROVED):
            self._update_status(name, "idle")

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        if tool_name == "bash":
            return run_bash(args["command"])
        if tool_name == "read_file":
            return read_file(args["filepath"])
        if tool_name == "write_file":
            return write_file(args["filepath"], args["content"])
        if tool_name == "edit":
            return edit_file(args["filepath"], args["old_string"], args["new_string"])
        if tool_name == "send_message":
            return BUS.send(sender, args["to"], args["content"], args.get("msg_type", "message"))
        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(sender), indent=2, ensure_ascii=False)
        return f"Unknown tool: {tool_name}"

    def _teammate_tools(self) -> list:
        return [
            {"type": "function", "function": {"name": "bash", "description": "Run a shell command.",
             "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
            {"type": "function", "function": {"name": "read_file", "description": "Read file contents.",
             "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
            {"type": "function", "function": {"name": "write_file", "description": "Write content to file.",
             "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}}},
            {"type": "function", "function": {"name": "edit", "description": "Edit file by find-replace.",
             "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["filepath", "old_string", "new_string"]}}},
            {"type": "function", "function": {"name": "send_message", "description": "Send message to teammate.",
             "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}}},
            {"type": "function", "function": {"name": "read_inbox", "description": "Read and drain inbox.",
             "parameters": {"type": "object", "properties": {}}}},
        ]

    def _update_status(self, name: str, status: str):
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]

    def delete(self, name: str) -> str:
        """Delete a teammate: remove from config, clean inbox, stop thread."""
        member = self._find_member(name)
        if not member:
            return f"Error: Teammate '{name}' not found."
        # Remove from config
        self.config["members"] = [m for m in self.config["members"] if m["name"] != name]
        self._save_config()
        # Remove inbox file
        inbox_path = INBOX_DIR / f"{name}.jsonl"
        if inbox_path.exists():
            inbox_path.unlink()
        # Remove input queue
        with teammate_input_lock:
            teammate_input_queues.pop(name, None)
        # Remove from threads
        self.threads.pop(name, None)
        return f"Deleted teammate '{name}'."


# Global teammate manager
TEAM = TeammateManager(TEAM_DIR)


# -- Lead tools for quality review --
def review_deliverable(path: str, requirements: str = "") -> str:
    """Review a teammate's deliverable file for quality."""
    content = read_file(path)
    if content.startswith("Error: File not found"):
        # 可能是传入了队友名而不是文件路径，给出引导
        member = TEAM._find_member(path)
        if member:
            return (
                f"'{path}' 是一个队友名，不是文件路径。请先通过 send_message 向 {path} 发送消息"
                f"询问他创建了什么文件，或者用 bash dir 命令查看工作目录中的文件。"
            )
        return content
    return (
        f"[DELIVERABLE REVIEW]\n"
        f"File: {path}\n"
        f"Requirements: {requirements or '(general review)'}\n"
        f"--- Content ---\n{content[:8000]}"
    )


def request_redo(teammate: str, feedback: str, task_description: str = "") -> str:
    """Send rework feedback to a teammate."""
    member = TEAM._find_member(teammate)
    if not member:
        return f"Error: Teammate '{teammate}' not found."
    TEAM._update_status(teammate, STATUS_REWORKING)
    verdict_msg = f"REDO: {feedback}\nPlease redo your work addressing this feedback."
    BUS.send("lead", teammate, verdict_msg, "review_verdict")
    return f"Sent REDO request to '{teammate}' with feedback:\n  {feedback}"


def approve_deliverable(teammate: str, feedback: str = "") -> str:
    """Approve a teammate's deliverable."""
    member = TEAM._find_member(teammate)
    if not member:
        return f"Error: Teammate '{teammate}' not found."
    TEAM._update_status(teammate, STATUS_APPROVED)
    approval_msg = f"APPROVED: {feedback or 'Good job!'}"
    BUS.send("lead", teammate, approval_msg, "review_verdict")
    return f"Approved '{teammate}'s deliverable. {feedback}"


def delete_teammate(teammate: str) -> str:
    """Delete a teammate from the team. Use this after a teammate has been approved and their work is complete."""
    return TEAM.delete(teammate)


# ═══════════════════════════════════════════════════════════
# 异步后台任务管理器 - 实现真正的异步执行
# ═══════════════════════════════════════════════════════════

class BackgroundManager:
    """
    后台任务管理器 - 实现"发射后不管"的异步非阻塞执行
    
    核心设计:
    1. 多线程并行 - 每个后台任务在独立线程执行
    2. 通知队列注入 - 任务完成后加入队列，下次 LLM 调用前注入对话
    3. 线程安全 - 使用 Lock 保护共享的 notification_queue
    4. 超时保护 - 默认 300 秒超时，防止无限挂起
    5. UUID 标识 - 每个任务生成唯一 task_id
    """
    
    def __init__(self):
        self._tasks = {}  # task_id -> {thread, status, start_time, command}
        self._notification_queue = queue.Queue()
        self._lock = threading.Lock()
    
    def run(self, command: str, timeout: int = 300) -> str:
        """
        启动后台任务，立即返回 task_id
        
        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）
        
        Returns:
            task_id: 任务标识符
        """
        task_id = str(uuid.uuid4())[:8]
        
        def _worker():
            start_time = time.time()
            with self._lock:
                self._tasks[task_id] = {
                    "status": "running",
                    "start_time": start_time,
                    "command": command,
                    "output": None,
                    "error": None,
                }
            
            try:
                result = run_bash(command)
                elapsed = time.time() - start_time
                
                with self._lock:
                    self._tasks[task_id]["status"] = "completed"
                    self._tasks[task_id]["output"] = result
                    self._tasks[task_id]["elapsed"] = elapsed
                
                # 加入通知队列
                self._notification_queue.put({
                    "task_id": task_id,
                    "status": "completed",
                    "output": result,
                    "elapsed": elapsed,
                })
            except Exception as e:
                with self._lock:
                    self._tasks[task_id]["status"] = "error"
                    self._tasks[task_id]["error"] = str(e)
                
                self._notification_queue.put({
                    "task_id": task_id,
                    "status": "error",
                    "error": str(e),
                })
        
        thread = threading.Thread(target=_worker, daemon=True)
        with self._lock:
            self._tasks[task_id] = {"thread": thread, "status": "starting"}
        thread.start()
        
        return f"🚀 后台任务已启动：task_id={task_id}\n   命令：{command}\n   使用 check_task('{task_id}') 查询进度"
    
    def check(self, task_id: str) -> str:
        """查询任务状态"""
        with self._lock:
            if task_id not in self._tasks:
                return f"❌ 未找到任务：{task_id}"
            
            task = self._tasks[task_id]
            status = task.get("status", "unknown")
            elapsed = time.time() - task.get("start_time", time.time())
            
            if status == "running":
                return f"⏳ 任务 {task_id} 正在运行中... (已运行 {elapsed:.1f}s)\n   命令：{task.get('command', '?')}"
            elif status == "completed":
                output = task.get("output", "")[:500]
                return f"✅ 任务 {task_id} 已完成 (耗时 {task.get('elapsed', 0):.1f}s)\n   输出：{output}"
            elif status == "error":
                return f"❌ 任务 {task_id} 失败：{task.get('error', 'unknown error')}"
            else:
                return f"❓ 任务 {task_id} 状态未知：{status}"
    
    def drain_notifications(self) -> list:
        """清空并返回所有通知（用于注入 LLM 对话）"""
        notifications = []
        while not self._notification_queue.empty():
            try:
                notifications.append(self._notification_queue.get_nowait())
            except queue.Empty:
                break
        return notifications


# 全局后台任务管理器实例
BACKGROUND = BackgroundManager()

# ── 异步引擎全局状态 ──
# 这些变量由 __main__ 初始化，LeadEngine 后台线程读取/修改
current_session_id = None
history = []
command_log_path = ""
script_path = ""


def check_task(task_id: str) -> str:
    """检查后台任务状态的工具函数"""
    return BACKGROUND.check(task_id)


def get_background_notifications() -> str:
    """获取并清空后台任务通知（在 LLM 调用前注入）"""
    notifications = BACKGROUND.drain_notifications()
    if not notifications:
        return ""
    
    parts = ["<background-results>"]
    for n in notifications:
        if n["status"] == "completed":
            parts.append(
                f"[✅ 任务完成] task_id={n['task_id']}, 耗时={n['elapsed']:.1f}s\n"
                f"输出：{n['output'][:1000]}"
            )
        elif n["status"] == "error":
            parts.append(
                f"[❌ 任务失败] task_id={n['task_id']}\n"
                f"错误：{n['error']}"
            )
    parts.append("</background-results>")
    return "\n".join(parts)


# ── 上下文大小跟踪与压缩 ─────────────────────────

CONTEXT_WARN_THRESHOLD = 60000  # token，超过此值显示警告
CONTEXT_COMPRESS_THRESHOLD = 80000  # token，超过此值自动压缩
CONTEXT_CRITICAL_THRESHOLD = 100000  # token，超过此值强制压缩


def estimate_tokens(messages: list) -> int:
    """
    估算消息列表的 token 数。
    粗略估算: 1 token ≈ 3 个字符（中英文混合）
    """
    total_chars = 0
    for msg in messages:
        # 统计 content
        content = msg.get("content") or ""
        total_chars += len(content)

        # 统计 tool_calls（如果有）
        for tc in msg.get("tool_calls", []):
            total_chars += len(json.dumps(tc.get("function", {}), ensure_ascii=False))

        # 统计 reasoning_content（如果有）
        rc = msg.get("reasoning_content") or ""
        total_chars += len(rc)

    # 粗略: 1 token ≈ 3 chars
    return max(1, total_chars // 3)


def format_context_summary(messages: list) -> str:
    """格式化上下文信息，用于显示"""
    total_msgs = len(messages)
    total_tokens = estimate_tokens(messages)

    # 按角色统计
    role_counts = {}
    for msg in messages:
        role = msg.get("role", "?")
        role_counts[role] = role_counts.get(role, 0) + 1

    parts = [f"{role}={count}" for role, count in sorted(role_counts.items())]
    role_summary = ", ".join(parts)

    bar = ""
    ratio = total_tokens / CONTEXT_COMPRESS_THRESHOLD
    if ratio >= 1.0:
        bar = "🟥" * 10
    elif ratio >= 0.8:
        filled = int(ratio * 10)
        bar = "🟧" * filled + "⬜" * (10 - filled)
    elif ratio >= 0.5:
        filled = int(ratio * 10)
        bar = "🟨" * filled + "⬜" * (10 - filled)
    else:
        filled = int(ratio * 10)
        bar = "🟩" * filled + "⬜" * (10 - filled)

    warn = ""
    if total_tokens >= CONTEXT_CRITICAL_THRESHOLD:
        warn = " ⚠️⚠️ 超过临界值，需要压缩！"
    elif total_tokens >= CONTEXT_COMPRESS_THRESHOLD:
        warn = " ⚠️ 超过压缩阈值"
    elif total_tokens >= CONTEXT_WARN_THRESHOLD:
        warn = " ⚡ 接近阈值"

    return (
        f"\033[36m📊 上下文: {total_tokens:>6,} token | "
        f"{total_msgs:>3} 条消息 ({role_summary})\033[0m\n"
        f"\033[36m   {bar} {total_tokens/1000:.1f}K/{CONTEXT_COMPRESS_THRESHOLD/1000:.0f}K{warn}\033[0m"
    )


def compress_context(messages: list) -> list:
    """
    压缩上下文：保留 system prompt，将最早的用户-助手对话轮次压缩为摘要。
    使用 DeepSeek 自身来生成摘要。
    """
    if len(messages) <= 3:
        return messages  # 太短，不需要压缩

    # 保留 system 和最近 2 轮对话
    system_msgs = [m for m in messages if m.get("role") == "system"]
    # 取最近的 N 条消息保留（至少保留最后 4 条工具/助手消息）
    keep_count = min(20, max(6, len(messages) // 3))
    recent_msgs = messages[-keep_count:]

    # 需要压缩的中间部分（去掉 system 和最近的部分）
    middle_start = len(system_msgs)
    middle_end = len(messages) - keep_count
    if middle_start >= middle_end:
        return messages  # 中间没内容，不压缩

    middle_msgs = messages[middle_start:middle_end]

    # 构建摘要 prompt
    summary_parts = []
    for m in middle_msgs:
        role = m.get("role", "?")
        content = (m.get("content") or "")[:200]
        if content:
            summary_parts.append(f"[{role}]: {content}")

    if not summary_parts:
        return messages

    summary_text = "\n".join(summary_parts)
    compress_prompt = (
        "以下是之前对话的部分内容，请用一段话总结其中已经完成的任务、关键决定和重要信息。"
        "总结要简洁但保留所有重要上下文（用户需求、项目路径、已做的修改、遇到的错误等）。\n\n"
        f"{summary_text[:8000]}\n\n"
        "请只输出总结，不要加前缀后缀。"
    )

    print(f"\033[33m🧹 正在压缩上下文 ({len(middle_msgs)} 条消息 → 1 条摘要)...\033[0m")

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": compress_prompt}],
            max_completion_tokens=1024,
            temperature=0.5,
            timeout=60.0,
        )
        summary = resp.choices[0].message.content or ""
        print(f"\033[32m   ✅ 压缩完成，摘要长度: {len(summary)} 字符\033[0m")

        # 构建新消息列表: system + 摘要 + 最近消息
        compressed = list(system_msgs)
        compressed.append({
            "role": "system",
            "content": system_msgs[0].get("content", "") + (
                "\n\n--- 以下是对之前对话的摘要（较早的对话已压缩，保留关键信息）---\n"
                f"{summary}"
            )
        })
        compressed.extend(recent_msgs)
        return compressed

    except Exception as e:
        print(f"\033[31m   ❌ 压缩失败: {e}，保持原样\033[0m")
        return messages
# ── 会话管理（多轮对话保存与加载） ─────────────────────
SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")
SESSION_INDEX = os.path.join(SESSION_DIR, "index.json")


def init_session_dir():
    """确保 sessions 目录和 index.json 存在"""
    os.makedirs(SESSION_DIR, exist_ok=True)
    if not os.path.exists(SESSION_INDEX):
        with open(SESSION_INDEX, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)


def load_session_index() -> list:
    """加载会话索引列表"""
    init_session_dir()
    try:
        with open(SESSION_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_session_index(index: list):
    """保存会话索引列表"""
    with open(SESSION_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def create_session(title: str = "新对话") -> str:
    """创建新会话，返回 session_id"""
    init_session_dir()
    index = load_session_index()
    # 生成不重复的 session_id
    existing_ids = {s["id"] for s in index}
    n = 1
    while f"session_{n:03d}" in existing_ids:
        n += 1
    session_id = f"session_{n:03d}"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_info = {
        "id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }
    index.append(session_info)
    save_session_index(index)
    # 创建空的会话文件
    session_path = os.path.join(SESSION_DIR, f"{session_id}.json")
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump({"info": session_info, "messages": []}, f, ensure_ascii=False)
    print(f"\033[32m📝 创建新会话: {session_id} ({title})\033[0m")
    return session_id


def save_session(session_id: str, messages: list, title: str = None):
    """保存会话消息到文件"""
    session_path = os.path.join(SESSION_DIR, f"{session_id}.json")
    index = load_session_index()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 更新索引中的信息
    for item in index:
        if item["id"] == session_id:
            item["updated_at"] = now
            item["message_count"] = len(messages)
            if title:
                item["title"] = title
            break

    save_session_index(index)

    # 找到当前 session 的 info
    info = next((i for i in index if i["id"] == session_id), {})
    session_data = {
        "info": info,
        "messages": messages,
    }
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)


def load_session(session_id: str) -> list:
    """加载指定会话的消息列表，返回 None 表示失败"""
    session_path = os.path.join(SESSION_DIR, f"{session_id}.json")
    if not os.path.exists(session_path):
        return None
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            session_data = json.load(f)
        return session_data.get("messages", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return None


def list_sessions() -> list:
    """列出所有会话（按 updated_at 倒序排列）"""
    index = load_session_index()
    # 按更新时间倒序排列
    index.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return index


def auto_title_from_messages(messages: list) -> str:
    """从消息中自动提取标题（取第一条 user 消息的前30字符）"""
    for msg in messages:
        if msg.get("role") == "user":
            content = (msg.get("content") or "").strip()
            if content:
                title = content[:30]
                if len(content) > 30:
                    title += "..."
                return title
    return "新对话"


def delete_session(session_id: str):
    """删除指定会话"""
    index = load_session_index()
    index = [i for i in index if i["id"] != session_id]
    save_session_index(index)
    session_path = os.path.join(SESSION_DIR, f"{session_id}.json")
    if os.path.exists(session_path):
        os.remove(session_path)
    print(f"\033[33m🗑️ 已删除会话: {session_id}\033[0m")


def clean_tool_messages(messages: list) -> list:
    """
    清理没有对应 tool_calls 的 tool 角色消息。
    当上下文压缩或加载旧会话时，可能出现 tool 消息缺失对应的 assistant tool_calls，
    这会导致 API 报错: "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
    """
    cleaned = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        # 如果是 tool 消息，检查前面是否有对应的 tool_calls
        if msg.get('role') == 'tool':
            # 向前查找最近的 assistant 消息（带 tool_calls）
            has_tool_call = False
            for j in range(i-1, -1, -1):
                prev = messages[j]
                if prev.get('role') == 'assistant':
                    tool_calls = prev.get('tool_calls')
                    if tool_calls:
                        # 检查这个 tool_call_id 是否匹配
                        tool_call_ids = [tc.get('id') for tc in tool_calls]
                        if msg.get('tool_call_id') in tool_call_ids:
                            has_tool_call = True
                    break
                elif prev.get('role') == 'tool':
                    continue  # 继续往前找
                else:
                    break  # 遇到 user/system 消息就停止

            if has_tool_call:
                cleaned.append(msg)
            # 否则跳过这条无效的 tool 消息
        else:
            cleaned.append(msg)
        i += 1

    return cleaned


def chat(messages: list):
    """发送对话历史，循环处理大模型发过来的工具调用，直到模型返回纯文本。"""
    iteration = 0
    max_iterations = 50  # 防止无限循环
    consecutive_empty_inbox = 0  # 连续空收件箱计数
    first_empty_time = None      # 首次发现收件箱为空的时间，用于超时判断
    
    while iteration < max_iterations:
        iteration += 1
        # 在调用 API 前清理无效的 tool 消息（避免压缩/加载旧会话导致的 tool_calls 配对丢失）
        # 使用切片赋值原地修改，保持 messages 引用不变
        cleaned = clean_tool_messages(messages)
        messages[:] = cleaned

        print(f"\033[36m[DEBUG] 第 {iteration} 次调用 API，messages 数量={len(messages)}\033[0m")

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_completion_tokens=1024,
                temperature=0.7,
                tools=TOOLS,
                tool_choice="auto",
                timeout=120.0,
            )
        except Exception as e:
            print(f"\033[31m[ERROR] API 调用失败：{e}\033[0m")
            # 添加错误消息到历史
            error_msg = {"role": "assistant", "content": f"API 调用失败：{str(e)[:200]}"}
            messages.append(error_msg)
            return
        
        msg = response.choices[0].message

        # 调试输出：查看模型返回的内容
        content_preview = repr(msg.content)[:50] if msg.content else "None"
        tool_calls_count = len(msg.tool_calls) if msg.tool_calls else 0
        print(f"\033[36m[DEBUG] 第{iteration}轮：content={content_preview}, tool_calls={tool_calls_count}\033[0m")

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
                # ── Agent Teams 工具 ──────────────────────────
                elif tc.function.name == "spawn_teammate":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m🧑‍💻 Spawning teammate: {args['name']} ({args['role']})...\033[0m")
                    output = TEAM.spawn(args["name"], args["role"], args["prompt"])
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "list_teammates":
                    output = TEAM.list_all()
                    print(f"\033[33m👥 Teammates:\n{output}\033[0m")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "send_message":
                    args = json.loads(tc.function.arguments)
                    to_name = args["to"]
                    # 检查队友是否已经 approved（线程已退出，收不到消息）
                    member = TEAM._find_member(to_name)
                    if member and member.get("status") == "approved":
                        output = (f"WARNING: '{to_name}' 的状态是 'approved'（已完成任务，线程已退出），"
                                  f"他收不到这条消息！请使用 spawn_teammate 创建新的队友，"
                                  f"不要给已完成的队友发消息。")
                        print(f"\033[33m⚠ {output[:200]}\033[0m")
                    else:
                        print(f"\033[33m📨 Sending message to {to_name}: {args['content'][:80]}...\033[0m")
                        output = BUS.send("lead", to_name, args["content"], args.get("msg_type", "message"))
                        print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "read_inbox":
                    inbox = BUS.read_inbox("lead")
                    if not inbox:
                        consecutive_empty_inbox += 1
                        # 记录首次为空的时间，实现时间超时（最多等待60秒）
                        if first_empty_time is None:
                            first_empty_time = time.time()
                        wait_elapsed = time.time() - first_empty_time
                        # 时间超时优先于次数超时
                        if wait_elapsed > 60:
                            output = ("HARD_STOP: 等待队友超过60秒，收件箱仍为空。队友可能已退出或仍在工作中。"
                                      "请 STOP checking inbox and respond to the user saying tasks are in progress.")
                            consecutive_empty_inbox = 999
                        elif consecutive_empty_inbox >= 6:
                            # 连续6次空收件箱 → 硬性停止轮询循环
                            output = ("HARD_STOP: 收件箱已连续6次为空。队友可能已经退出（approved状态）或尚未启动。"
                                      "请 STOP checking inbox and respond to the user saying tasks are in progress.")
                            consecutive_empty_inbox = 999  # 标志位，后续循环会检测到
                        elif consecutive_empty_inbox >= 3:
                            output = "[] (收件箱连续3次为空。请不要再检查收件箱了，先回复用户说队友还在工作中，等队友主动发消息来)"
                        else:
                            time.sleep(2)
                            output = "[] (收件箱为空，队友还在工作中)"
                    else:
                        consecutive_empty_inbox = 0  # 有消息了，重置计数
                        first_empty_time = None      # 重置时间超时
                        output = json.dumps(inbox, indent=2, ensure_ascii=False)
                    print(f"\033[33m📬 Lead inbox:\n{output[:300]}\033[0m")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output or "(empty)",
                    })
                elif tc.function.name == "broadcast":
                    args = json.loads(tc.function.arguments)
                    output = BUS.broadcast("lead", args["content"], TEAM.member_names())
                    print(f"\033[33m📢 Broadcast: {output}\033[0m")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "review_deliverable":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m🔍 Reviewing: {args['path']}...\033[0m")
                    output = review_deliverable(args["path"], args.get("requirements", ""))
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "request_redo":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m🔄 Requesting redo from {args['teammate']}...\033[0m")
                    output = request_redo(args["teammate"], args["feedback"], args.get("task_description", ""))
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "approve_deliverable":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m✅ Approving {args['teammate']}'s deliverable...\033[0m")
                    output = approve_deliverable(args["teammate"], args.get("feedback", ""))
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                elif tc.function.name == "delete_teammate":
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m🗑️ Deleting teammate {args['teammate']}...\033[0m")
                    output = delete_teammate(args["teammate"])
                    print(output[:200])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
                # ── GitHub MCP 工具 (由官方 MCP 服务器提供) ──
                elif tc.function.name in MCP_TOOL_NAMES:
                    args = json.loads(tc.function.arguments)
                    print(f"\033[33m🐙 MCP: {tc.function.name} {str(args)[:80]}...\033[0m")
                    try:
                        output = mcp_client.call_tool(tc.function.name, args)
                    except Exception as e:
                        output = f"MCP 调用出错: {e}"
                    print(output[:300])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": output,
                    })
            # 继续循环，让模型看工具结果后生成最终回答
            # 但如果连续空收件箱达到6次，强制退出循环
            if consecutive_empty_inbox >= 999:
                print("\033[31m[HARD STOP] 连续多次空收件箱，中断工具调用循环\033[0m")
                # 添加一条消息告诉模型停下来
                messages.append({
                    "role": "assistant",
                    "content": "我已经等待了足够长的时间，但队友们没有发来消息。让我先回复用户当前的进展。",
                })
                break
            continue
        
        # 模型返回纯文本 → 记入历史并结束
        # 如果 content 为空但也没有 tool_calls，说明模型认为回答完成了，给一个默认提示
        final_content = msg.content
        if not final_content:
            final_content = "（思考完毕，但没有输出内容。请重新提问或补充更多信息。）"

        final_msg = {"role": "assistant", "content": final_content}
        if msg.reasoning_content:
            final_msg["reasoning_content"] = msg.reasoning_content
        messages.append(final_msg)
        print(f"\033[32m[DEBUG] chat() 函数返回，最终回答长度={len(final_content)}\033[0m")
        return
    
    # 达到最大迭代次数
    print(f"\033[31m[ERROR] 达到最大迭代次数 ({max_iterations})，强制结束\033[0m")
    timeout_msg = {"role": "assistant", "content": f"⚠️ 工具调用次数过多（超过{max_iterations}次），已强制结束。请检查是否有循环调用问题。"}
    messages.append(timeout_msg)


# ═══════════════════════════════════════════════════════════
# LeadEngine - 后台 Lead 工作线程（实现真正的异步输入）
# ═══════════════════════════════════════════════════════════
"""
LeadEngine 实现了"队友在工作，主线程还能接收用户输入"的核心需求。

设计原理:
  主线程: 永远在 input() 循环中，用户输入 → 入队 lead_input_queue
  Lead 线程: 从队列取输入，调用 chat() 处理，同时定期检查 teammates 发来的 inbox

  这样用户在 Lead LLM 思考/队友干活时，可以随时输入新指令。
  新输入会等到当前 chat() 结束后被处理。
"""

# ── 全局 Lead 输入队列和线程锁 ──
lead_input_queue = queue.Queue()
lead_inbox_event = threading.Event()  # 队友发来消息时设置，唤醒 Lead 线程
history_lock = threading.Lock()       # 保护 history 列表的并发访问

# ── 队友（管家）独立输入队列 ──
# 每个 spawn 的队友都有自己独立的输入队列
# 主线程检测 @name 前缀路由到对应队列
teammate_input_queues = {}           # {name: Queue}
teammate_input_lock = threading.Lock() # 保护 teammate_input_queues


def lead_worker_loop():
    """
    Lead 工作线程的主循环。
    从队列获取用户输入，处理 inbox 消息，调用 chat()。
    运行在独立的后台线程，不阻塞主线程的 input()。
    """
    while True:
        # ── 1. 检查用户输入（非阻塞，超时 1 秒） ──
        try:
            query = lead_input_queue.get(timeout=1.0)
        except queue.Empty:
            query = None

        # ── 2. 检查队友发来的 inbox 消息 ──
        inbox = BUS.read_inbox("lead")

        # ── 3. 有输入或 inbox 消息才处理 ──
        if query is not None:
            with history_lock:
                # 记录输入到日志
                log_record = {
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "program": script_path,
                    "input": query,
                }
                try:
                    with open(command_log_path, "a", encoding="utf-8") as log_f:
                        log_f.write(json.dumps(log_record, ensure_ascii=False) + "\n")
                except Exception:
                    pass

                history.append({"role": "user", "content": query})

                # ── 自动生成对话标题（第一条用户消息） ──
                index = load_session_index()
                for item in index:
                    if item["id"] == current_session_id and item["title"] == "新对话":
                        non_system = [m for m in history if m.get("role") != "system"]
                        if len(non_system) == 1:
                            new_title = auto_title_from_messages(history)
                            item["title"] = new_title
                            save_session_index(index)
                            print(f"\n\033[32m📝 对话标题已设为: {new_title}\033[0m")
                        break

            # Lead 处理用户输入（chat 内部会修改 history）
            chat(history)

            # ── 自动保存 + 上下文压缩 + 显示回答 ──
            with history_lock:
                title = auto_title_from_messages(history)
                save_session(current_session_id, history, title)
                print()
                print(format_context_summary(history))
                print()

                current_tokens = estimate_tokens(history)
                if current_tokens >= CONTEXT_COMPRESS_THRESHOLD:
                    history_mod = compress_context(history)
                    history[:] = history_mod  # 原地替换
                    print()
                    print(format_context_summary(history))
                    title = auto_title_from_messages(history)
                    save_session(current_session_id, history, title)
                    print()

                # 显示最终回答
                for m in reversed(history):
                    if m.get("role") == "assistant" and m.get("content"):
                        content = m.get("content", "")
                        if content:
                            print(f"\n\033[32m🤖 助手回答:\033[0m\n{content}\n")
                        break

        elif inbox:
            # ── 只有 inbox 消息，没有用户输入 ──
            with history_lock:
                inbox_text = json.dumps(inbox, indent=2, ensure_ascii=False)
                history.append({
                    "role": "user",
                    "content": f"<inbox>\n{inbox_text}\n</inbox>",
                })

            # Lead 处理 inbox 消息
            chat(history)

            with history_lock:
                title = auto_title_from_messages(history)
                save_session(current_session_id, history, title)

        else:
            # ── 没有新消息，短暂休眠 ──
            time.sleep(0.2)


def start_lead_engine():
    """启动 Lead 后台工作线程"""
    thread = threading.Thread(target=lead_worker_loop, daemon=True, name="LeadWorker")
    thread.start()
    return thread


if __name__ == "__main__":
    # ════════════════════════════════════════════════════════════
    # --prompt 参数支持：非交互式单次查询模式
    # ════════════════════════════════════════════════════════════
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, help="单次查询模式：传入 prompt 后直接输出结果并退出")
    parser.add_argument("--server", action="store_true", help="持久运行 HTTP 服务器模式")
    parser.add_argument("--port", type=int, default=5799, help="服务器端口（默认 5799）")
    args, unknown = parser.parse_known_args()

    if args.prompt:
        # 非交互式模式：静默初始化 → 处理 prompt → 输出结果 → 退出
        # 将初始化日志输出到 stderr，确保 stdout 只输出最终回答
        import contextlib
        import io

        _real_stdout = sys.stdout
        sys.stdout = sys.stderr  # 初始化期间的 print 走 stderr

        # ── 初始化（与交互式模式一致）─────────────────────
        script_path = os.path.abspath(__file__)
        print(f"\033[32m📄 当前 Agent 代码文件: {script_path}\033[0m")

        script_dir = os.path.dirname(script_path)
        os.chdir(script_dir)
        load_dotenv(override=True)
        local_token = os.getenv("GITHUB_TOKEN", "")
        if local_token:
            GITHUB_TOKEN = local_token

        mcp_tools = init_mcp_server()
        if mcp_tools:
            TOOLS.extend(mcp_tools)
            print(f"\033[32m🔧 工具总数: {len(TOOLS)} (本地 + GitHub MCP)\033[0m\n")
        else:
            print(f"\033[33m🔧 工具总数: {len(TOOLS)} (仅本地，GitHub MCP 未加载)\033[0m\n")

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
        system_prompt += "\n\n【总结经验规则】每当完成一个任务（解决 Bug、实现功能、部署成功），或者用户说「成功了」「做好了」等表示任务完成的语句时，必须将本次的经验教训总结写入 经验记录.md，包括：遇到的问题、原因分析、解决方案、注意事项。格式参照已有条目。"
        system_prompt += f"\n\n你正在运行的 agent 代码文件路径是: {script_path}"

        # ── 包含完整的团队协作规则 ──────────────────────
        system_prompt += (
            '\n\n【重要：团队协作模式】'
            '\n你是一个团队 Lead（队长），你有多个队友（Agents）可用。'
            '\n当用户给你一个任务时，你的首要职责是：'
            '\n1. 分析任务，拆解为子任务'
            '\n2. 用 spawn_teammate 将子任务派发给合适的队友（指定好名字、角色、任务描述）'
            '\n3. 用 read_inbox 等待队友完成并提交审查'
            '\n4. 审查队友交付物，用 approve_deliverable 批准或用 request_redo 要求返工'
            '\n5. 用 delete_teammate 清理已完成的队友'
            '\n'
            '\n禁止行为：'
            '\n- \u274c 不要亲自用 bash/read_file/edit/write_file 等工具去做本该队友做的事'
            '\n- \u274c 不要自己做代码修改、文件操作等，这些都应该派给队友'
            '\n- \u274c 不要代替用户做决定——如果你不确定如何拆解任务，先问用户'
            '\n'
            '\n你应该做的：'
            '\n- \u2705 任务一来，先想「这个任务能不能派给队友？」'
            '\n- \u2705 派发时给队友清晰的指令（要做什么、输出什么文件、质量标准）'
            '\n- \u2705 队友工作时，你可以询问用户更多细节，或者等待队友完成'
            '\n- \u2705 队友提交审查后，审阅交付物，批准或要求修改'
            '\n- \u2705 队友完成后，删除队友，释放资源'
            '\n'
            '\n注意：你仍然可以使用 bash/read_file 等工具做小量的信息查询或验证，'
            '\n但任何实质性的「做事」（写代码、改代码、写文档、搜索等），都必须派给队友。'
        )

        snippets = []
        if experience_content:
            snippets.append(
                "以下是你过往的经验教训记录，请仔细阅读并避免重复犯错：\n"
                f"{experience_content}"
            )
        if user_content:
            snippets.append(
                "以下是用记的做事方法与偏好，请遵循：\n"
                f"{user_content}"
            )
        if snippets:
            system_prompt += "\n\n---\n" + "\n\n---\n".join(snippets)

        _ = create_session("单次查询")
        history = [{"role": "system", "content": system_prompt}]
        print()
        print(format_context_summary(history))
        print()

        # ── 处理 prompt ────────────────────────────────
        history.append({"role": "user", "content": args.prompt})
        chat(history)

        # ── 提取最终回答并输出到 stdout ────────────────
        sys.stdout = _real_stdout  # 恢复 stdout
        final_answer = ""
        for msg in reversed(history):
            if msg.get("role") == "assistant" and msg.get("content"):
                final_answer = msg["content"]
                break
        if final_answer:
            print(final_answer)

        # ── 清理退出 ──────────────────────────────────
        if mcp_client:
            mcp_client.shutdown()
        exit(0)

    elif args.server:
        # ════════════════════════════════════════════════════════════
        # --server 模式：持久运行 HTTP 服务器，保持对话上下文
        # ════════════════════════════════════════════════════════════
        port = args.port

        # 重定向初始化日志到 stderr
        _real_stdout = sys.stdout
        sys.stdout = sys.stderr

        # ── 初始化（与 --prompt 模式一致）─────────────────────
        script_path = os.path.abspath(__file__)
        print(f"启动 Agent Server (port={port})...")
        script_dir = os.path.dirname(script_path)
        os.chdir(script_dir)
        load_dotenv(override=True)
        local_token = os.getenv("GITHUB_TOKEN", "")
        if local_token:
            GITHUB_TOKEN = local_token

        mcp_tools = init_mcp_server()
        if mcp_tools:
            TOOLS.extend(mcp_tools)
            print(f"工具总数: {len(TOOLS)} (本地 + GitHub MCP)")
        else:
            print(f"工具总数: {len(TOOLS)} (仅本地)")

        # 加载经验记录和用户偏好
        def _load_md(filename, label):
            path = os.path.join(os.getcwd(), filename)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                print(f"已加载 {label} ({len(content)} 字符)")
                return content
            return ""

        experience_content = _load_md("经验记录.md", "经验记录")
        user_content = _load_md("user.md", "用户偏好")

        system_prompt = "你是一个有帮助的助手，当你修改完代码后，请用 bash 工具运行 python 文件名.py 来验证修改是否成功，如果出错则修复"
        system_prompt += "\n\n【核心规则】每一次有失败的操作（工具调用报错、测试不通过、抓取失败、路径错误等），都必须分析原因，将经验教训总结写入 经验记录.md，格式参照已有条目。这非常重要，请严格遵守。"
        system_prompt += "\n\n【总结经验规则】每当完成一个任务（解决 Bug、实现功能、部署成功），或者用户说「成功了」「做好了」等表示任务完成的语句时，必须将本次的经验教训总结写入 经验记录.md，包括：遇到的问题、原因分析、解决方案、注意事项。格式参照已有条目。"
        system_prompt += f"\n\n你正在运行的 agent 代码文件路径是: {script_path}"

        # ── 包含完整的团队协作规则 ──────────────────────
        system_prompt += (
            '\n\n【重要：团队协作模式】'
            '\n你是一个团队 Lead（队长），你有多个队友（Agents）可用。'
            '\n当用户给你一个任务时，你的首要职责是：'
            '\n1. 分析任务，拆解为子任务'
            '\n2. 用 spawn_teammate 将子任务派发给合适的队友（指定好名字、角色、任务描述）'
            '\n3. 用 read_inbox 等待队友完成并提交审查'
            '\n4. 审查队友交付物，用 approve_deliverable 批准或用 request_redo 要求返工'
            '\n5. 用 delete_teammate 清理已完成的队友'
            '\n'
            '\n禁止行为：'
            '\n- ❌ 不要亲自用 bash/read_file/edit/write_file 等工具去做本该队友做的事'
            '\n- ❌ 不要自己做代码修改、文件操作等，这些都应该派给队友'
            '\n- ❌ 不要代替用户做决定——如果你不确定如何拆解任务，先问用户'
            '\n'
            '\n你应该做的：'
            '\n- ✅ 任务一来，先想「这个任务能不能派给队友？」'
            '\n- ✅ 派发时给队友清晰的指令（要做什么、输出什么文件、质量标准）'
            '\n- ✅ 队友工作时，你可以询问用户更多细节，或者等待队友完成'
            '\n- ✅ 队友提交审查后，审阅交付物，批准或要求修改'
            '\n- ✅ 队友完成后，删除队友，释放资源'
            '\n'
            '\n注意：你仍然可以使用 bash/read_file 等工具做小量的信息查询或验证，'
            '\n但任何实质性的「做事」（写代码、改代码、写文档、搜索等），都必须派给队友。'
        )

        snippets = []
        if experience_content:
            snippets.append(
                "以下是你过往的经验教训记录，请仔细阅读并避免重复犯错：\n"
                f"{experience_content}"
            )
        if user_content:
            snippets.append(
                "以下是用记的做事方法与偏好，请遵循：\n"
                f"{user_content}"
            )
        if snippets:
            system_prompt += "\n\n---\n" + "\n\n---\n".join(snippets)

        _ = create_session("agent-server")
        history_lock = threading.Lock()
        history = [{"role": "system", "content": system_prompt}]

        # ── HTTP Handler ────────────────────────────────────
        class AgentHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # 不输出请求日志

            def do_GET(self):
                if self.path == "/health":
                    self._send_json(200, {"status": "ok", "history_len": len(history)})
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self):
                if self.path == "/chat":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_length))
                    prompt = body.get("prompt", "").strip()
                    if not prompt:
                        self._send_json(400, {"error": "prompt is required"})
                        return
                    if len(prompt) > 10000:
                        self._send_json(400, {"error": "prompt too long"})
                        return

                    # 使用锁保护 history 并发访问
                    with history_lock:
                        history.append({"role": "user", "content": prompt})
                        # 调用 chat() 处理
                        chat(history)
                        # 提取最后一条 assistant 回答
                        answer = ""
                        for msg in reversed(history):
                            if msg.get("role") == "assistant" and msg.get("content"):
                                answer = msg["content"]
                                break

                    self._send_json(200, {"answer": answer})

                elif self.path == "/reset":
                    with history_lock:
                        history = [history[0]]  # 只保留 system prompt
                    self._send_json(200, {"status": "ok"})

                else:
                    self._send_json(404, {"error": "not found"})

            def _send_json(self, status, data):
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        # 启动服务器
        server = HTTPServer(("127.0.0.1", port), AgentHandler)
        print(f"Agent Server 已启动: http://127.0.0.1:{port}")
        sys.stdout = _real_stdout  # 恢复 stdout
        print(f"http://127.0.0.1:{port}")  # 输出地址到 stdout，方便 Rust 检测
        sys.stdout.flush()

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nAgent Server 关闭中...")
        finally:
            server.server_close()
            if mcp_client:
                mcp_client.shutdown()
            exit(0)

    # ── 获取当前脚本的绝对路径 ──────────────────────────
    script_path = os.path.abspath(__file__)
    print(f"\033[32m📄 当前 Agent 代码文件: {script_path}\033[0m")

    # ── 启动 GitHub 官方 MCP 服务器，合并工具列表 ──────────
    script_dir = os.path.dirname(script_path)
    os.chdir(script_dir)  # 切换到脚本目录以加载 .env
    load_dotenv(override=True)  # 刷新环境变量
    # 重新加载脚本目录下的 .env
    local_token = os.getenv("GITHUB_TOKEN", "")
    if local_token:
        GITHUB_TOKEN = local_token  # if 块在模块级作用域内，直接赋值即可

    mcp_tools = init_mcp_server()
    if mcp_tools:
        TOOLS.extend(mcp_tools)
        print(f"\033[32m🔧 工具总数: {len(TOOLS)} (本地 + GitHub MCP)\033[0m\n")
    else:
        print(f"\033[33m🔧 工具总数: {len(TOOLS)} (仅本地，GitHub MCP 未加载)\033[0m\n")

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
    system_prompt += "\n\n【总结经验规则】每当完成一个任务（解决 Bug、实现功能、部署成功），或者用户说「成功了」「做好了」等表示任务完成的语句时，必须将本次的经验教训总结写入 经验记录.md，包括：遇到的问题、原因分析、解决方案、注意事项。格式参照已有条目。"
    # 告诉大模型当前运行的 Agent 代码文件路径
    system_prompt += f"\n\n你正在运行的 agent 代码文件路径是: {script_path}"

    # ── 优先派发队友的工作模式 ──────────────────────────
    # Lead 必须优先使用 spawn_teammate 将任务派发给队友，
    # 而不是亲自用 bash/read_file/edit 等工具去做。
    # 队友是独立的 LLM Agent，可以自主完成任务并提交审查。
    system_prompt += (
        '\n\n【重要：团队协作模式】'
        '\n你是一个团队 Lead（队长），你有多个队友（Agents）可用。'
        '\n当用户给你一个任务时，你的首要职责是：'
        '\n1. 分析任务，拆解为子任务'
        '\n2. 用 spawn_teammate 将子任务派发给合适的队友（指定好名字、角色、任务描述）'
        '\n3. 用 read_inbox 等待队友完成并提交审查'
        '\n4. 审查队友交付物，用 approve_deliverable 批准或用 request_redo 要求返工'
        '\n5. 用 delete_teammate 清理已完成的队友'
        '\n'
        '\n禁止行为：'
        '\n- \u274c 不要亲自用 bash/read_file/edit/write_file 等工具去做本该队友做的事'
        '\n- \u274c 不要自己做代码修改、文件操作等，这些都应该派给队友'
        '\n- \u274c 不要代替用户做决定——如果你不确定如何拆解任务，先问用户'
        '\n'
        '\n你应该做的：'
        '\n- \u2705 任务一来，先想「这个任务能不能派给队友？」'
        '\n- \u2705 派发时给队友清晰的指令（要做什么、输出什么文件、质量标准）'
        '\n- \u2705 队友工作时，你可以询问用户更多细节，或者等待队友完成'
        '\n- \u2705 队友提交审查后，审阅交付物，批准或要求修改'
        '\n- \u2705 队友完成后，删除队友，释放资源'
        '\n'
        '\n注意：你仍然可以使用 bash/read_file 等工具做小量的信息查询或验证，'
        '\n但任何实质性的「做事」（写代码、改代码、写文档、搜索等），都必须派给队友。'
    )

    snippets = []
    if experience_content:
        snippets.append(
            "以下是你过往的经验教训记录，请仔细阅读并避免重复犯错：\n"
            f"{experience_content}"
        )
    if user_content:
        snippets.append(
            "以下是用记的做事方法与偏好，请遵循：\n"
            f"{user_content}"
        )
    if snippets:
        system_prompt += "\n\n---\n" + "\n\n---\n".join(snippets)
    # ── 创建新会话 ──────────────────────────────────
    current_session_id = create_session("新对话")
    history = [{"role": "system", "content": system_prompt}]
    print()
    print(format_context_summary(history))
    print()
    print("\033[33m💡 命令:")
    print("  /历史对话  — 查看并加载历史对话")
    print("  /新对话    — 保存当前对话，开始新对话")
    print("  /agents    — 列出所有活跃的 Agent（包括 Lead 和队友）")
    print("  @队友名    — 直接给指定队友发消息（如 @诗人 写首诗）")
    print("  q / exit   — 退出")
    print("  Ctrl+J     — 在输入中插入换行符\033[0m\n")
    # ── 命令记录文件路径（command-test.txt 与脚本同目录） ─────
    command_log_path = os.path.join(os.path.dirname(script_path), "command-test.txt")

    # ── 设置模块级全局变量，供 Lead 工作线程使用 ──
    # 注意: 要使用 import __main__ 的方式写入模块级对象
    import builtins
    # 直接用 global 写法，因为当前在模块顶层
    globals()['history'] = history
    globals()['current_session_id'] = current_session_id
    globals()['command_log_path'] = command_log_path
    globals()['script_path'] = script_path

    # ⭐ 启动 Lead 后台工作线程
    # 从此以后，用户的输入都通过 lead_input_queue 传递，
    # lead_worker_loop 在后台线程处理 chat()、保存、压缩等
    start_lead_engine()
    print(f"\033[32m⚡ Lead 引擎已启动，输入将异步处理\033[0m")

    # ── prompt_toolkit 单行输入：Enter 直接发送，支持粘贴大段文字（Ctrl+J 插入换行）──
    prompt_session = PromptSession()
    while True:
        try:
            query = prompt_session.prompt('you>>> ')
        except (EOFError, KeyboardInterrupt):
            print("\n\033[33m正在保存当前对话...\033[0m")
            save_session(current_session_id, history)
            if mcp_client:
                mcp_client.shutdown()
            print("\n\033[33m退出\033[0m")
            exit(0)

        query = query.strip()
        if not query:
            continue

        # 检测退出命令
        if query.lower() in ("q", "exit"):
            print("\033[33m正在保存当前对话...\033[0m")
            save_session(current_session_id, history)
            if mcp_client:
                mcp_client.shutdown()
            print("\033[33m退出\033[0m")
            exit(0)

        # ── 特殊命令处理 ──────────────────────────────────

        # ── /历史对话 ──────────────────────────────────
        if query.strip() == "/历史对话":
            sessions = list_sessions()
            if not sessions:
                print("\033[33m📭 暂无历史对话\033[0m")
                continue
            print("\n\033[36m📋 历史对话列表：\033[0m")
            print("\033[36m" + "-" * 60 + "\033[0m")
            for i, s in enumerate(sessions, 1):
                msg_count = s.get("message_count", 0)
                date_str = s.get("updated_at", "")[:16]
                title = s.get("title", "未命名")
                marker = " ← 当前" if s["id"] == current_session_id else ""
                print(f"  \033[33m{i:>2}.\033[0m {title} \033[90m({msg_count}条, {date_str})\033[0m\033[32m{marker}\033[0m")
            print("\033[36m" + "-" * 60 + "\033[0m")
            print("  输入 \033[33m编号\033[0m 加载对应对话，输入 \033[33m0\033[0m 取消，输入 \033[33md+编号\033[0m 删除（如 d3）")
            choice = input("\033[36m选择 >\033[0m ").strip()

            if choice == "0" or choice == "":
                continue

            # 删除操作
            if choice.startswith("d") or choice.startswith("D"):
                num_str = choice[1:].strip()
                if num_str.isdigit():
                    idx = int(num_str)
                    if 1 <= idx <= len(sessions):
                        s = sessions[idx - 1]
                        if s["id"] == current_session_id:
                            print("\033[31m⚠️  不能删除当前对话\033[0m")
                            continue
                        delete_session(s["id"])
                        print(f"\033[33m已删除: {s['title']}\033[0m")
                    else:
                        print("\033[31m无效编号\033[0m")
                else:
                    print("\033[31m格式错误，请用 d+编号 如 d3\033[0m")
                continue

            # 加载操作
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(sessions):
                    selected = sessions[idx - 1]
                    # 如果选择的是当前会话，不做任何事
                    if selected["id"] == current_session_id:
                        print("\033[33m已是当前对话\033[0m")
                        continue
                    # 保存当前对话
                    save_session(current_session_id, history)
                    # 加载选择的对话
                    loaded_msgs = load_session(selected["id"])
                    if loaded_msgs:
                        # 加锁保护，避免与 Lead 线程冲突
                        with history_lock:
                            current_session_id = selected["id"]
                            history = loaded_msgs
                        print(f"\n\033[32m✅ 已加载对话: {selected.get('title', '未命名')}\033[0m")
                        print(f"\033[36m📊 共 {len(history)} 条消息\033[0m")
                        # 显示最后一条助手消息
                        for m in reversed(history):
                            if m.get("role") == "assistant" and m.get("content"):
                                print(f"\n\033[90m--- 最后回复 ---\033[0m")
                                print(m["content"])
                                break
                    else:
                        print(f"\033[31m❌ 加载失败: 会话文件损坏或不存在\033[0m")
                else:
                    print("\033[31m无效编号\033[0m")
            else:
                print("\033[31m输入无效，请输入编号、d+编号 或 0\033[0m")
            continue

        # ── /新对话 ──────────────────────────────────
        if query.strip() == "/新对话":
            # 先保存当前对话
            title = auto_title_from_messages(history)
            save_session(current_session_id, history, title)
            # 创建新会话
            current_session_id = create_session()
            # 重置 history，只保留 system prompt
            with history_lock:
                history = [m for m in history if m.get("role") == "system"]
            print("\033[32m✅ 已开始新对话！\033[0m")
            print(format_context_summary(history))
            continue

        # ── /agents 或 /list ── 列出所有活跃的队友 ──
        if query.strip() in ("/agents", "/list"):
            print("\n\033[36m📋 活跃的 Agent 列表：\033[0m")
            print("\033[36m" + "-" * 60 + "\033[0m")
            # Lead
            print(f"  \033[33mlead\033[0m (Lead 主线程) — @lead 消息内容")
            # 已 spawn 的队友
            with teammate_input_lock:
                for name, q in sorted(teammate_input_queues.items()):
                    # 获取状态
                    member = TEAM._find_member(name)
                    status = member["status"] if member else "unknown"
                    qsize = q.qsize()
                    status_color = {
                        "working": "\033[32m",
                        "under_review": "\033[33m",
                        "reworking": "\033[31m",
                        "approved": "\033[34m",
                        "idle": "\033[90m",
                    }.get(status, "\033[0m")
                    print(f"  {status_color}@{name}\033[0m ({status}) {'📨' if qsize else ''} — @{name} 消息内容")
            print(f"\n\033[33m💡 使用 @队友名 消息内容 直接与队友对话\033[0m")
            print("\033[36m" + "-" * 60 + "\033[0m\n")
            continue

        # ── 异步对话流程 ──────────────────────────────────
        # 不再直接调用 chat(history)，而是将输入放入队列
        # LeadEngine 的后台线程会从队列取输入并处理
        # 这样用户可以在 Lead 思考/队友干活时继续输入
        
        # 自动生成对话标题（第一条用户消息）
        index = load_session_index()
        for item in index:
            if item["id"] == current_session_id and item["title"] == "新对话":
                non_system = [m for m in history if m.get("role") != "system"]
                if len(non_system) == 1:
                    new_title = auto_title_from_messages(history)
                    item["title"] = new_title
                    save_session_index(index)
                    print(f"\033[32m📝 对话标题已设为: {new_title}\033[0m")
                break

        # ⭐ 异步关键：把用户输入放入队列，立即返回继续 input()
        # 支持 @name 前缀路由到指定队友的输入队列
        if query.startswith("@"):
            # 格式: @队友名 消息内容  → 路由到该队友的输入队列
            space_idx = query.find(" ")
            if space_idx == -1:
                # 只有 @name 没有消息内容
                target = query[1:].strip()
                body = ""
            else:
                target = query[1:space_idx].strip()
                body = query[space_idx+1:].strip()

            if not target:
                print("\033[33m格式: @队友名 消息内容\033[0m")
                continue

            # 检查是否为 Lead
            if target.lower() == "lead":
                lead_input_queue.put(body or "(打招呼)")
                print(f"\033[36m📩 消息已路由到 Lead\033[0m")
                continue

            # 检查是否为某个队友
            with teammate_input_lock:
                target_queue = teammate_input_queues.get(target)

            if target_queue:
                target_queue.put(body or "(打招呼)")
                print(f"\033[36m📩 消息已路由到 @{target}\033[0m")
                # 同步日志记录
                log_record = {
                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "program": script_path,
                    "input": f"@{target} {body}",
                }
                try:
                    with open(command_log_path, "a", encoding="utf-8") as log_f:
                        log_f.write(json.dumps(log_record, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            else:
                # 不认识的队友名，列出所有可用的
                active_list = []
                if lead_input_queue:
                    active_list.append("lead")
                with teammate_input_lock:
                    active_list.extend(teammate_input_queues.keys())
                print(f"\033[31m❌ 未找到队友 '{target}'。当前可用: {', '.join(active_list)}\033[0m")
                print(f"\033[33m💡 使用 @队友名 消息 格式直接与队友对话\033[0m")
            continue

        # 普通输入 → 走 Lead 的异步队列
        lead_input_queue.put(query)
