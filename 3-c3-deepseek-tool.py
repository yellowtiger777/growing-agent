#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""

这次开始增加了tools，这个tools里面现在只有一个 bash工具，  这个tools会在调用deepseek api时，作为一个参数传入
deepseek大模型来判断 需要调取工具，就会用run-bash函数中调取bash工具中的某一个命令，然后把结果都返回给deepseek。deepseek最终觉得不需要调取工具了，返回了总结性的结果，就是任务执行完了。
重点在于 chat函数。
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
    },
}]

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
            # 继续循环，让模型看工具结果
            continue

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
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        chat(history)
        print(history[-1]["content"])
