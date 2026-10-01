# 从零实现 AI Agent

用 DeepSeek 的对话接口，从「单次工具调用」逐步做到「多步推理 + 联网搜索」。四个脚本各自独立，可以按顺序阅读和运行。

模型通过 OpenAI 兼容接口调用 `deepseek-chat`。算术、时间和搜索由本地函数执行，模型只负责决定何时调用、以及如何根据返回结果组织答案。

## 学习路径

| 文件 | 能力 |
| --- | --- |
| `tool_demo.py` | 一个计算器。模型判断要不要调用，调用一次后生成最终回答。 |
| `multi_tool.py` | 计算器 + 当前时间。同一轮可以调用多个工具，结果汇总后再回答。 |
| `react_agent.py` | 多步循环。每轮观察工具结果，再决定继续调用还是给出答案，最多 6 步。 |
| `search_agent.py` | 在多步循环上增加 DuckDuckGo 搜索，用于新闻和实时信息。 |

## 环境

- Python 3.10+
- [DeepSeek API Key](https://platform.deepseek.com/)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

把 `.env` 里的 `DEEPSEEK_API_KEY` 换成自己的密钥。`.env` 已被 `.gitignore` 忽略，`.env.example` 只保留变量名。

## 运行

```powershell
python tool_demo.py
python multi_tool.py
python react_agent.py
python search_agent.py
```

启动后在终端输入问题，输入 `q` 退出。

可以试这些问法：

- `tool_demo.py`：`123 * 456 等于多少`
- `multi_tool.py`：`现在几点？再算一下 (10+5)/3`
- `react_agent.py`：`先告诉我现在的时间，再把小时数乘以 60`
- `search_agent.py`：`今天有什么科技新闻`

`react_agent.py` 和 `search_agent.py` 会在终端打印每一步调用的工具名、参数和观察结果。搜索结果较长，终端只显示前 200 个字符，完整内容仍会回传给模型。

## 调用流程

1. 把用户问题放进 `messages`，并附上工具说明书（函数名、说明、参数）。
2. 请求模型。若返回 `tool_calls`，按名称在 `available_tools` 里找到对应函数并执行。
3. 把执行结果以 `role: tool` 写回对话。
4. `tool_demo.py` 和 `multi_tool.py` 只再请求一次，让模型生成最终回答。
5. `react_agent.py` 和 `search_agent.py` 重复第 2、3 步，直到模型不再调用工具，或达到 `max_steps`（默认 6）。达到上限时返回「已达到最大步数，任务未完成。」

## 工具

| 名称 | 作用 | 出现在 |
| --- | --- | --- |
| `calculator` | 计算数学表达式 | 全部脚本 |
| `get_current_time` | 返回本地时间，格式 `YYYY-MM-DD HH:MM:SS` | `multi_tool.py` 及之后 |
| `web_search` | 用 DuckDuckGo 搜索，取前 5 条标题和摘要 | `search_agent.py` |

`calculator` 使用去掉内置函数的 `eval` 计算表达式，只适合本地演示，不要把它暴露给不受信任的输入。
