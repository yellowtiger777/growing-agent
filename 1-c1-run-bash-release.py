#!/usr/bin/env python3
"""
大模型只是思考，agent是能动手操作！
agent的实质是 可以对文件进行操作，最重要的就是这个bash功能。我们首先就要理解怎样用程序去操作其他文件。


"""

import os
import re
import sys
import subprocess
import shutil


# ── 平台检测 ────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"

# ── bash 可用性检测（只测一次，缓存结果） ──────────────
_HAS_BASH = None


def _check_bash_available() -> bool:
    """检测系统是否安装了 bash（如 Git Bash / WSL）"""
    global _HAS_BASH
    if _HAS_BASH is not None:
        return _HAS_BASH
    try:
        result = subprocess.run(
            ["bash", "--version"],
            capture_output=True, text=True,
            timeout=5,
        )
        _HAS_BASH = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _HAS_BASH = False
    return _HAS_BASH


# ── bash → cmd 翻译表 ────────────────────────────────────
# 当 Windows 上没装 bash 时，自动把常见 shell 命令转为 cmd 能懂的写法
# 格式: (正则匹配模式, 替换字符串)
BASH_TO_CMD_TRANSLATIONS = [
    # ── 文件查看 ──
    (r'\bcat\s+',                    'type '),            # cat file → type file
    (r'\bless\s+',                   'more '),            # less file → more file
    (r'\bgrep\s+',                   'findstr '),         # grep → findstr

    # ── 文件管理 ──
    (r'\bcp\s+',                     'copy '),            # cp src dst → copy src dst
    (r'\bmv\s+',                     'move '),            # mv src dst → move src dst
    (r'\brm\s+-rf\s+',              'rmdir /s /q '),     # rm -rf dir → rmdir /s /q dir
    (r'\brm\s+-f\s+',               'del /f '),          # rm -f file → del /f file
    (r'\brm\s+',                     'del '),             # rm file → del file
    (r'\btouch\s+',                  r'type nul > '),     # touch file → type nul > file（近似）

    # ── 目录操作 ──
    (r'\bls\s+',                     'dir '),             # ls args → dir args
    (r'\bls$',                       'dir'),              # ls（无参数）
    (r'\bpwd$',                      'echo %cd%'),        # pwd → echo %cd%

    # ── 环境变量: $VAR / ${VAR} → %VAR%
    (r'\$\{?(\w+)\}?',               r'%\1%'),            # $HOME → %HOME%

    # ── 清屏 ──
    (r'\bclear$',                    'cls'),              # clear → cls

    # ── 路径: 正斜杠 → 反斜杠（Windows 路径习惯，但 / 通常也行，这里保险转换）
    # 注意：只有在 Windows 无 bash 时才触发这一条
    # 不对路径做强制转换，/ 在 cmd 里也基本可用，避免误伤
]


def _translate_bash_to_cmd(command: str) -> tuple:
    """将 bash 命令翻译为 Windows cmd 命令。
    返回 (翻译后命令, 是否发生了翻译)。
    """
    if not IS_WINDOWS:
        return command, False

    # 如果系统有 bash 可用，不需要翻译
    if _check_bash_available():
        return command, False

    translated = command
    changed = False

    for pattern, replacement in BASH_TO_CMD_TRANSLATIONS:
        new_translated = re.sub(pattern, replacement, translated)
        if new_translated != translated:
            changed = True
            translated = new_translated

    return translated, changed


# ── 安全过滤（4 层） ────────────────────────────────────
# 在 Agent 场景中，模型会自主决定执行什么命令。必须多角度
# 拦截危险操作，不能依赖单一的简单黑名单。

# 第1层：危险正则模式（解决空格变体、大小写绕过问题）
DANGEROUS_PATTERNS = [
    # ── 文件系统毁灭性操作 ──
    r"\brm\s+.*-rf",                 # rm -rf 任意路径
    r"\brm\s+.*-r\s",                # rm -r 递归删除
    r"\brm\s+.*--recursive",         # rm --recursive
    r"\brmdir\b",                    # rmdir
    r"\bdel\b",                      # Windows del
    r"\bformat\s+\w:",               # format C: 等
    r"\bdd\s+if=",                   # dd 磁盘操作
    r"\bmkfs\.",                     # mkfs 格式化
    r"\bfdisk\b",                    # fdisk 分区

    # ── 系统控制 ──
    r"\bshutdown\b",                 # 关机
    r"\breboot\b",                   # 重启
    r"\binit\s+[06]",                # init 0 / init 6
    r"\bsystemctl\s+(poweroff|halt|suspend)",  # systemd 关机
    r"\bhalt\b",                     # 停机

    # ── 权限提升 ──
    r"\bsudo\b",                     # sudo
    r"\bsu\s+-",                     # su - root
    r"\bchmod\s+777",                # 危险放宽权限
    r"\bchmod\s+[0-7]*7[0-7]*7\b",  # 任何含"其他用户可写"的 chmod
    r"\bchown\b",                    # 改变所有者

    # ── 远程代码执行（管道到 shell） ──
    r"\bcurl\b.*\|\s*(ba)?sh",      # curl xxx | bash
    r"\bwget\b.*\|\s*(ba)?sh",      # wget xxx | sh
    r"\bcurl\b.*\|\s*python",       # curl xxx | python
    r"\bwget\b.*-O\s*-\s*\|\s*(ba)?sh",  # wget -O - | bash

    # ── Fork 炸弹 / 拒绝服务 ──
    r":\(\)\s*\{",                   # fork bomb 特征
    r"\{[^}]*:\|:&\s*\}",            # fork bomb 变体

    # ── 进程屠杀 ──
    r"\bkill\s+-9",                  # kill -9 强制杀进程
    r"\bpkill\b",                    # pkill
    r"\btaskkill\b",                 # Windows taskkill

    # ── 系统文件覆盖 ──
    r">\s*/etc/",                    # 重定向覆盖 /etc/
    r">\s*/System32/",               # 重定向覆盖 Windows System32
    r">\s*/boot/",                   # 重定向覆盖 /boot/
    r">\s*~/\.bashrc",               # 覆盖 bashrc
    r">\s*~/\.profile",              # 覆盖 profile

    # ── 注册表（Windows） ──
    r"\breg\s+(delete|add\b.*\bHKLM)",  # 注册表危险操作
]

# 第2层：严格关键词（整个 token 匹配，防子串误伤）
DANGEROUS_TOKENS = [
    "> /dev/sda",                    # 覆盖磁盘设备
    "> /dev/hda",
    "> /dev/nvme",
    "mkfs.",                         # 格式化文件系统
    "chkdsk /f",                     # Windows 磁盘修复（有风险）
]

# 第3层：全部大写的命令如果看起来危险就拦（防编码绕过）
# 去掉命令中的所有特殊字符后，检查是否包含危险词根
DANGEROUS_ROOTS = [
    "shutdown", "reboot", "mkfs", "fdisk", "format",
]


def run_bash(command: str, timeout: int = 120) -> str:
    """安全执行 shell 命令并返回输出。

    智能执行策略：
    - Linux/macOS：直接用 bash 执行
    - Windows 有 bash（Git Bash/WSL）：直接用 bash 执行
    - Windows 无 bash：自动将 bash 命令翻译为 cmd 命令后执行
    """
    # ── 1. 安全检查（4 层） ──

    # 第1层：正则模式匹配（忽略大小写）
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"Error: Dangerous command blocked (matched: {pattern})"

    # 第2层：严格 token 匹配
    cmd_lower = command.lower()
    for token in DANGEROUS_TOKENS:
        if token.lower() in cmd_lower:
            return f"Error: Dangerous command blocked (matched token: {token})"

    # 第3层：净化后检查（去除特殊字符，防编码绕过）
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', command).lower()
    for root in DANGEROUS_ROOTS:
        if root.lower() in cleaned:
            return f"Error: Dangerous command blocked (matched root: {root})"

    # 第4层：长度限制（拒绝超长命令，防混淆攻击）
    if len(command) > 2000:
        return "Error: Command too long (max 2000 chars)"

    # ── 2. 平台自适应：Windows 无 bash 时自动翻译 ──
    translated_command, was_translated = _translate_bash_to_cmd(command)

    if was_translated:
        # 用 cmd.exe 执行翻译后的命令
        executor = "cmd.exe"
        exec_args = ["cmd.exe", "/c", translated_command]
        note = "[auto-translated bash→cmd]"
    else:
        # 用 bash 执行原命令
        executor = "bash"
        exec_args = ["bash", "-c", command]
        note = ""

    # ── 3. 执行 ──
    try:
        r = subprocess.run(
            exec_args,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

        # 合并 stdout + stderr
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if not out:
            out = "(no output)"

        # 截断超长输出
        if len(out) > 50000:
            out = out[:50000]

        # 如果发生了翻译，附加提示信息
        if was_translated:
            out = f"[bash→cmd] {out}"

        return out

    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"


# ── 演示 ────────────────────────────────────────────────
if __name__ == "__main__":
    # 标题
    print("=" * 50)
    print("run_bash 演示")
    print(f"  平台: {'Windows' if IS_WINDOWS else 'Linux/macOS'}")
    print(f"  bash 可用: {_check_bash_available()}")
    print("=" * 50)

    # 示例 1：基本命令
    print("\n[1] 基本命令：")
    print(run_bash("echo Hello ,welcome to  growing-agent"))

    # 示例 2：获取 Python 版本
    print("\n[2] 获取 Python 版本：")
    print(run_bash("python --version"))

    # 示例 3：当前目录
    print("\n[3] 当前目录：")
    print(run_bash("pwd"))

    # 示例 4：危险命令被拦截
    print("\n[4] 危险命令被拦截：")
    print(run_bash("sudo rm -rf /"))

    # 示例 5：不存在的命令
    print("\n[5] 不存在的命令（会捕获 stderr）：")
    print(run_bash("this_command_does_not_exist"))

    # 实例6，用命令新建一个文件
    print("\n[6] 用命令创建一个文件 + 写入内容")
    print(run_bash('echo "# 我们要做一个 逐步成长的agent的教程" > growing-agent-read-me.txt'))

    # 实例7，搜索该目录下的所有txt文件
    print("\n[7] 搜索 .txt 文件：")
    print(run_bash('ls -1 *.txt'))

    # 实例8：多行命令 — 找到第一个 txt 文件并显示内容
    print("\n[8] 多行命令（找第一个 txt 文件并显示内容）：")
    result = run_bash("""
        first_file=$(ls -1 *.txt 2>/dev/null | head -n 1)
        if [ -n "$first_file" ]; then
            echo "找到文件: $first_file"
            echo "--- 内容如下 ---"
            cat "$first_file"
        else
            echo "没有找到 txt 文件"
        fi
    """)
    print(result)

    # 实例9：建 .env + sed 改代码
    print("\n[9] 多命令串联（建 .env + sed 改代码）：")
    script_dir = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    print(f"   脚本所在目录: {script_dir}")
    print(run_bash(f"""echo 'DEEPSEEK_API_KEY=your-api-key-here' > "{script_dir}/.env" && echo 'DEEPSEEK_BASE_URL=https://api.deepseek.com' >> "{script_dir}/.env" && sed -i 's|api_key="your-api-key-here"|api_key=os.getenv("DEEPSEEK_API_KEY")|; s|base_url="https://api.deepseek.com"|base_url=os.getenv("DEEPSEEK_BASE_URL")|' "{script_dir}/c2-deepseek-api.py" """))

    # 实例10：新建1.txt，写入内容，复制到2.txt
    print("\n[10] 新建1.txt 写入内容，再复制到2.txt：")
    script_dir = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    print(run_bash(f'echo 中国人民万岁！ > "{script_dir}/1.txt" && cp "{script_dir}/1.txt" "{script_dir}/2.txt"'))
    print("  1.txt 内容：")
    print(run_bash(f'cat "{script_dir}/1.txt"'))
    print("  2.txt 内容：")
    print(run_bash(f'cat "{script_dir}/2.txt"'))
