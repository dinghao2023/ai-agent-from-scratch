import os
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
from ddgs import DDGS

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式，例如 2+3*4 或 (10+5)/3",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "要计算的数学表达式"}
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间（24小时制）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索实时信息，当需要了解新闻、最新事件、不知道的最新情况时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"],
            },
        },
    },
]

def calculator(expression):
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"计算失败: {e}"

def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def web_search(query):
    # 取前 5 条结果，拼成文本返回给模型
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "没有搜索到相关结果"
    lines = []
    for r in results:
        lines.append(f"标题：{r['title']}\n摘要：{r['body']}")
    return "\n\n".join(lines)

available_tools = {
    "calculator": calculator,
    "get_current_time": get_current_time,
    "web_search": web_search,
}

def run(user_input, max_steps=6):
    messages = [
        {"role": "system", "content": "你是一个可以使用工具的助手。需要最新信息时用 web_search，需要计算用 calculator，需要时间用 get_current_time。拿到结果后继续推理，信息足够后用中文给出最终答案。"},
        {"role": "user", "content": user_input},
    ]

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model="deepseek-chat", messages=messages, tools=tools
        )
        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content

        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)
            print(f"[第{step}步] 🔧 {name} {args}")

            result = available_tools[name](**args)
            print(f"[第{step}步] 👀 观察到：{result[:200]}...")  # 搜索结果长，只打印前200字

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

    return "已达到最大步数，任务未完成。"

if __name__ == "__main__":
    while True:
        q = input("\n请交给我一个任务（q 退出）：").strip()
        if q.lower() == "q":
            break
        print("\n🤖", run(q))