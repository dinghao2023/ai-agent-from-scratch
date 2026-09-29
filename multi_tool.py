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

# 工具说明书：现在有两个
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
            "description": "获取当前的日期和时间",
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

def run(user_input):
    messages = [{"role": "user", "content": user_input}]

    response = client.chat.completions.create(
        model="deepseek-chat", messages=messages, tools=tools
    )
    msg = response.choices[0].message
    messages.append(msg)

    if msg.tool_calls:
        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)
            print(f"🔧 调用：{name}，参数：{args}")

            result = available_tools[name](**args)
            print(f"➡️ 结果：{result}")

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

        final = client.chat.completions.create(
            model="deepseek-chat", messages=messages
        )
        return final.choices[0].message.content

    return msg.content

if __name__ == "__main__":
    while True:
        q = input("\n请提问（q 退出）：").strip()
        if q.lower() == "q":
            break
        print("🤖", run(q))