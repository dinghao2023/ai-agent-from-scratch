import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# 1. 声明：模型有哪些工具可以用（这是给模型看的"说明书"）
tools = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算数学表达式，例如 2+3*4 或 (10+5)/3",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "要计算的数学表达式",
                    }
                },
                "required": ["expression"],
            },
        },
    }
]

# 2. 真正干活的函数（注意：算数的是这段代码，不是模型）
def calculator(expression):
    print('expression:', expression)
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"计算失败: {e}"

available_tools = {"calculator": calculator}

def run(user_input):
    messages = [{"role": "user", "content": user_input}]

    # 第一次请求：模型判断要不要调工具
    response = client.chat.completions.create(
        model="deepseek-chat", messages=messages, tools=tools
    )
    msg = response.choices[0].message
    messages.append(msg)
    print('msg:', msg)

    if msg.tool_calls:
        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments)
            print(f"🔧 模型要调用：{name}，参数：{args}")

            result = available_tools[name](**args)
            print(f"➡️ 工具执行结果：{result}")

            # 把工具结果回传（role 必须是 tool）
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

        # 第二次请求：模型拿着结果，生成最终回答
        final = client.chat.completions.create(
            model="deepseek-chat", messages=messages
        )
        return final.choices[0].message.content

    return msg.content  # 不需要工具就直接答

if __name__ == "__main__":
    while True:
        q = input("\n请提问（q 退出）：").strip()
        if q.lower() == "q":
            break
        print("🤖", run(q))