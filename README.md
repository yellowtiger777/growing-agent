# 🌱 Growing Agent

从零到一，逐步构建一个真正能动手的 AI Agent。

## 项目理念

> 大模型只是思考，Agent 是能动手操作！

Agent 的实质是能对文件、系统进行操作，而最重要的能力之一就是 **执行 bash 命令**。本项目从最基础的 bash 执行器开始，每天递增一个版本，逐步构建完整的 Agent 能力。

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

## 发布计划

| 版本 | 内容 | 状态 |
|------|------|------|
| Day 1 | 最简 bash 执行器 | ✅ 已发布 |
| Day 2 | 接入 DeepSeek API | ⏳ |
| Day 3 | API 改进 | ⏳ |
| Day 4 | 引入函数调用 | ⏳ |
| ... | 逐步构建完整 Agent | 🚀 |

## 快速运行

```bash
python 1-c1-demo-run-bash.py
```

## 许可证

MIT
