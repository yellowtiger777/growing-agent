# 🌱 Growing Agent

> 🚀 **我们会持续更新！** 每天发布一个新版本，从简单到复杂，逐步构建一个真正能动手的 AI Agent。

从零到一，**一天一个版本**，见证一个 Agent 从最简单的 bash 执行器，成长为一个拥有多工具调用、MCP 集成、子 Agent 协作的完整框架。

---

## 📅 项目宣言

**大模型只是思考，Agent 是能动手操作！**

Agent 的实质是能对文件、系统进行操作，而最重要的能力之一就是 **执行 bash 命令**。

这个代码库会**持续更新**，每一版都比上一版更强大：

| 阶段 | 版本 | 内容 | 状态 |
|------|------|------|------|
| **基础** | Day 1 | 🔥 最简 Agent — 安全 bash 执行器 | ✅ **已发布** |
| | Day 1.1 | 改进版 — 更强安全检查 + bash→cmd 翻译 | ✅ **已发布** |
| | Day 2 | 🔥 调用 DeepSeek API — 一次对话 + 数据结构 | ✅ **已发布** |
| | Day 3 | API 改进与优化 | ⏳ |
| | Day 4 | 引入函数调用 (Tool Calling) | ⏳ |
| **工具** | Day 5 | 多工具并行执行 | ⏳ |
| | Day 6 | 输入循环 + 交互工作流 | ⏳ |
| | Day 7~9 | 新增 grep / edit / webfetch 工具 | ⏳ |
| **增强** | Day 10~12 | 搜索 API 集成 | ⏳ |
| | Day 13~14 | 读取经验记录 + 用户偏好 | ⏳ |
| **高级** | Day 15 | 命令执行记录 | ⏳ |
| | Day 16~17 | MCP 协议集成 (GitHub 工具) | ⏳ |
| | Day 18~19 | 子 Agent 多团队协作 | ⏳ |
| | Day 20+ | 更多高级特性... | 🚀 |

每个版本都在 `D:\project\create-claude-2` 的源码中真实存在，按计划逐天发布到 GitHub。

---

## Day 1：最简 Agent — 带安全过滤的 bash 执行器

**文件：** `1-c1-demo-run-bash.py`

一个安全可控的 bash 命令执行器，包含 10 个演示案例：

| 演示 | 说明 |
|------|------|
| 基本命令 | `echo` 输出 |
| 环境检测 | 获取 Python 版本、当前目录 |
| 安全拦截 | 危险命令（`sudo rm -rf /`）被拦截 |
| 错误处理 | 不存在的命令捕获 stderr |
| 文件操作 | 用命令创建文件、写入内容 |
| 搜索文件 | `ls` 查找 txt 文件 |
| 多行命令 | 找到文件并显示内容 |
| 多命令串联 | 建 `.env` + `sed` 改代码 |
| 文件复制 | 新建文件、复制内容 |

### 核心函数

```python
def run_bash(command: str, timeout: int = 120) -> str:
```

- ✅ 安全过滤：拦截 `rm -rf /`、`sudo`、`shutdown` 等危险命令
- ✅ 超时保护：命令超时自动终止
- ✅ 输出截断：超长输出自动截断（5 万字）
- ✅ 跨平台：Windows 下自动使用 Git Bash

---

## Day 1.1：改进版 — 更强的安全检查 + bash→cmd 自动适配

**文件：** `1-c1-run-bash-release.py`

在 Day 1 基础上的重大升级，核心改进：

### 🔐 4 层安全检查

| 层级 | 方式 | 说明 |
|------|------|------|
| 第 1 层 | 正则模式匹配 | 检测 rm -rf、sudo、curl\|bash 等 20+ 危险模式 |
| 第 2 层 | 严格 token 匹配 | 精确匹配磁盘设备、格式化等危险操作 |
| 第 3 层 | 净化后词根检查 | 去除特殊字符后查找危险词根，防编码绕过 |
| 第 4 层 | 长度限制 | 拒绝超长命令（>2000 字符），防混淆攻击 |

### 🔄 bash→cmd 自动翻译

当 Windows 上没有安装 bash（Git Bash/WSL）时，自动将常见 bash 命令翻译为 cmd 命令：

| bash 命令 | → | cmd 命令 |
|-----------|---|----------|
| `cat file` | → | `type file` |
| `ls` | → | `dir` |
| `grep` | → | `findstr` |
| `cp src dst` | → | `copy src dst` |
| `rm file` | → | `del file` |
| `rm -rf dir` | → | `rmdir /s /q dir` |
| `pwd` | → | `echo %cd%` |
| `$VAR` | → | `%VAR%` |

### 🧠 平台自适应

- Linux/macOS：直接使用 bash 执行
- Windows + 有 bash：使用 Git Bash/WSL 执行
- Windows + 无 bash：自动翻译后使用 cmd.exe 执行

---

## Day 2：调用 DeepSeek API — 一次对话 + 数据结构

**文件：** `2-c2-deepseek-api.py`

从 DeepSeek API 官方实现一次完整对话，核心目标是 **看懂大模型返回的数据结构**。

### 参数全覆盖

```python
response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[...],
    max_completion_tokens=1024,   # 最大输出 token
    temperature=0.7,              # 随机性
    top_p=0.9,                    # 核采样
    seed=42,                      # 固定随机种子（可复现）
    tools=None,                   # 工具定义列表 ← 未来重点
    tool_choice="auto",           # 工具选择策略
    stream=False,                 # 流式输出
)
```

### 返回数据结构一览

运行后会打印 DeepSeek 返回的**完整 JSON**，让你直观看到：

```json
{
  "id": "chatcmpl-xxx",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "你好！有什么可以帮助你的？"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "completion_tokens": ...,
    "prompt_tokens": ...,
    "total_tokens": ...
  },
  ...
}
```

> 💡 重点关注参数 `tools` — 后续所有 Agent 工具调用的基础就是从这里传给大模型的。

### 运行方式

```bash
python 2-c2-deepseek-api.py
# 然后输入你的问题，看看返回的数据长什么样
```

## 快速运行

```bash
# 运行 Day 1 版本
python 1-c1-demo-run-bash.py

# 运行 Day 2 版本（需要先配置 .env 中的 API Key）
python 2-c2-deepseek-api.py
```

## 如何跟进

- ⭐ **Star** 本仓库，第一时间收到更新通知
- 🔄 **每日一更**，每个版本独立可运行
- 📖 每个版本附有完整代码和注释，适合学习

## 许可证

MIT — 自由使用、修改、分享
