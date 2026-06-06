#!/usr/bin/env python3
"""
大模型只是思考，agent是能动手操作！
agent的实质是 可以对文件进行操作，最重要的就是这个bash功能。我们首先就要理解怎样用程序去操作其他文件。


"""

import os
import subprocess
import shutil


# ── 安全过滤 ────────────────────────────────────────────
# 在 Agent 场景中，模型会自主决定执行什么命令。为了防止意外
# 破坏，需要在执行前做一层简单的安全检查。
DANGEROUS_KEYWORDS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]


def run_bash(command: str, timeout: int = 120) -> str:
    """安全执行 shell 命令并返回输出。
    注意：Windows 调的是 cmd.exe，不认 bash 语法，所以显式指定 executable='bash'。
    """
    # 1. 安全检查
    if any(d in command for d in DANGEROUS_KEYWORDS):
        return "Error: Dangerous command blocked"

    # 2. 执行（显式用 bash，否则 Windows 走 cmd.exe）
    try:
        r = subprocess.run(
            ["bash", "-c", command],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

        # 3. 合并 stdout + stderr，让调用方看到输出内容+报错内容
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if not out:
            return "(no output)"

        # 4. 截断超长输出，防止淹没上下文
        return out[:50000] if len(out) > 50000 else out

    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except Exception as e:
        return f"Error: {e}"


# ── 演示 ────────────────────────────────────────────────
if __name__ == "__main__":
    # 这是弄个标题效果
    print("=" * 50)
    print("run_bash 演示")
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

    # 实例6，用命令新建一个文件，create-claude-read-me.txt
    print("\n[6] 用命令创建一个文件：   并且写入内容")
    print(run_bash('echo "# 我们要做一个 逐步成长的agent的教程" > growing-agent-read-me.txt'))

    #实例7     搜索该目录下的所有txt文件
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

    #实例9   多个命令，建立一个.env文件，写入内容，还要修改一下python文件的内容。
    print("\n[9] 多命令串联（建 .env + sed 改代码）：")
    # 用程序自身所在目录，避免硬编码路径；.env 里只放占位值，不写真实 key
    script_dir = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    print(f"   脚本所在目录: {script_dir}")
    print(run_bash(f"""echo 'DEEPSEEK_API_KEY=your-api-key-here' > "{script_dir}/.env" && echo 'DEEPSEEK_BASE_URL=https://api.deepseek.com' >> "{script_dir}/.env" && sed -i 's|api_key="your-api-key-here"|api_key=os.getenv("DEEPSEEK_API_KEY")|; s|base_url="https://api.deepseek.com"|base_url=os.getenv("DEEPSEEK_BASE_URL")|' "{script_dir}/c2-deepseek-api.py" """))


    #实例10   新建1.txt，写入内容，然后复制到2.txt
    print("\n[10] 新建1.txt 写入内容，再复制到2.txt：")
    script_dir = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
    print(run_bash(f'echo 中国人民万岁！ > "{script_dir}/1.txt" && cp "{script_dir}/1.txt" "{script_dir}/2.txt"'))
    print("  1.txt 内容：")
    print(run_bash(f'cat "{script_dir}/1.txt"'))
    print("  2.txt 内容：")
    print(run_bash(f'cat "{script_dir}/2.txt"'))

