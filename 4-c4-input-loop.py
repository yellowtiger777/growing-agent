#!/usr/bin/env python3
# Harness: the loop -- the model's first connection to the real world.
"""

这次开始增加了tools，这个tools里面现在有多个工具，有一个bash，还有一个weather（打印一段文字作为测试功能），  这个tools会在调用deepseek api时，作为一个参数传入
模型在生成的过程中，如果觉得需要调用工具，就会在生成的内容里包含一个tool_calls字段， 这个字段里会有工具调用的相关信息， 包括工具的名字和参数等
我们在这个harness里会检测到这个tool_calls字段， 然后根据工具调用的信息，去执行相应的工具（比如这里的bash工具），把工具的结果再以特定格式追加到对话历史里，再次发送给大模型， 让模型在下一轮生成时可以看到工具的结果，从而进行更进一步的推理或者回答。这些都是大模型提供给我们的用法

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
