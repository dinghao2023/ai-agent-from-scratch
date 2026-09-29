import os
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

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
]

def calculator(expression):
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"计算失败: {e}"

def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

available_tools = {"calculator": calculator, "get_current_time": get_current_time}

def run(user_input, max_steps=6):
    messages = [
        # 给模型一个系统提示，让它知道自己可以一步步来
        {"role": "system", "content": "你是一个可以使用工具的助手。需要时就调用工具，拿到结果后继续判断；信息足够后用中文给出最终答案。"},
        {"role": "user", "content": user_input},
    ]

    # 关键：循环，最多 max_steps 步，防止无限打转
    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model="deepseek-chat", messages=messages, tools=tools
        )
        msg = response.choices[0].message
        messages.append(msg)

        # 模型不再调用工具 = 任务完成，返回最终答案
        if not msg.tool_calls:
            return msg.content

        # 执行本轮所有工具调用，把结果喂回去，然后进入下一轮循环
        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)
            print(f"[第{step}步] 🔧 {name} {args}")

            result = available_tools[name](**args)
            print(f"[第{step}步] 👀 观察到：{result}")

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