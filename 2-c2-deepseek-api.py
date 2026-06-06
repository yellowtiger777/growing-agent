#!/usr/bin/env python3
"""
你要自行到deepseek的网站 https://www.deepseek.com/  api开放平台去注册一个账号，获得api key，然后填写到你这个程序所在文件夹
的.env文件里。程序才能顺利运行。
这个项目会一直使用deepseek api。后面的程序会教你使用cc switch，接上各种大模型的api
调用 DeepSeek API 实现一次对话
这是调用deepseek的  api，实现一次对话，我们看看deepseek返回给我们的json数据，是什么样子的。有哪些组成部分。
一定要注意看那个参数tools,以后的工具列表就是从这里传给大模型的
"""

import os
import httpx
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

# ── 配置 ────────────────────────────────────────────
# 环境变量 DEEPSEEK_API_KEY 在 .env 或系统中设置
# 使用无代理的 httpx 客户端，绕过系统代理直连 DeepSeek
_direct_http_client = httpx.Client(proxies=None, trust_env=False, verify=True)
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    http_client=_direct_http_client,
)
MODEL = "deepseek-v4-flash"


# ── 一次对话 ────────────────────────────────────────
def chat(messages: list):
    """发送一条消息，展示 chat.completions.create 的完整参数表。"""
    response = client.chat.completions.create(

        # ── 必填参数 ──────────────────────────────────
        model=MODEL,                            # 模型名
        messages=messages,

        # ── 输出控制 ──────────────────────────────────
        max_completion_tokens=1024,             # 最大输出 token 数（推荐，替代旧 max_tokens）
        # max_tokens=1024,                     # 旧写法，仍可用
        temperature=0.7,                        # 随机性 0~2，越大越随意
        top_p=0.9,                              # 核采样，0.9=只考虑概率前 90% 的词
        stop=None,                              # 停止词，遇到即停，如 ["\n\n"]
        seed=42,                                # 固定随机种子，可复现输出
        n=1,                                    # 生成几个候选回复

        # ── 频率惩罚 ──────────────────────────────────
        frequency_penalty=0.0,                  # -2.0~2.0，惩罚重复词
        presence_penalty=0.0,                   # -2.0~2.0，惩罚已出现过的词

        # ── 工具调用 ──────────────────────────────────
        tools=None,                             # 工具/函数定义列表
        tool_choice="auto",                     # auto / none / required / 指定工具

        # ── 输出格式 ──────────────────────────────────
        # response_format={"type": "json_object"},  # JSON 模式

        # ── 概率输出（调试用） ────────────────────────
        # logprobs=True,                        # 输出每个 token 的对数概率
        # top_logprobs=3,                       # 同时输出 top-3 候选词

        # ── 流式输出 ──────────────────────────────────
        stream=False,                           # True=逐 token 输出，需遍历 chunks

        # ── 其他 ─────────────────────────────────────
        timeout=60.0,                           # 请求超时（秒）
        # user="user-123",                      # 用户标识，用于监控滥用
        # extra_headers={"X-Test": "demo"},     # 额外 HTTP 头
        #extra_body={"thinking": {"type": "enabled"}},  # DeepSeek 特有：显式开启 thinking，返回 reasoning_content
    )
    return response


# ── 演示 ────────────────────────────────────────────
if __name__ == "__main__":
    import json

    print("=" * 50)
    print(f"DeepSeek API — 模型: {MODEL}")
    print("=" * 50)
    history=[                              # 对话历史
            {"role": "system", "content": "你是一个很有智慧的人"}   # 系统设定（可选）
        ]
    try:
        query = input("\033[36m input >> \033[0m")
    except (EOFError, KeyboardInterrupt):
        exit(0)
    if query.strip().lower() in ("q", "exit", ""):
        exit(0)
    history.append({"role": "user", "content": query})
    response = chat(history)

    # 把整个 response 转成字典，然后格式化打印
    data = response.model_dump()

    print("\n===== DeepSeek 返回的完整 JSON =====")
    print(json.dumps(data, indent=2, ensure_ascii=False))

    print("\n===== 以上呢，是我们展示整个返回数据的结构，但是给普通用户，我们只要展示核心的答案=====")
    answer = response.choices[0].message.content
    print(answer)