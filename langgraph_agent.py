import os
from datetime import datetime
from dotenv import load_dotenv
from ddgs import DDGS

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing import Annotated
from typing_extensions import TypedDict

load_dotenv()

# 用 @tool 装饰器声明工具（比手写 JSON 说明书省事，框架自动生成）
@tool
def calculator(expression: str) -> str:
    """计算数学表达式，例如 2+3*4 或 (10+5)/3"""
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"计算失败: {e}"

@tool
def get_current_time() -> str:
    """获取当前的日期和时间（24小时制）"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@tool
def web_search(query: str) -> str:
    """联网搜索实时信息，新闻、最新事件、不知道的最新情况时使用"""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "没有搜索到相关结果"
    return "\n\n".join(f"标题：{r['title']}\n摘要：{r['body']}" for r in results)

tools = [calculator, get_current_time, web_search]

# 模型：指向 DeepSeek，并把工具绑定上去
llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
llm_with_tools = llm.bind_tools(tools)

# State：图里流动的数据，这里就是不断累积的消息列表
class State(TypedDict):
    messages: Annotated[list, add_messages]

# agent 节点：调模型
def chatbot(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

# tools 节点：执行工具（框架预制好的）
tool_node = ToolNode(tools)

# 搭图：节点 + 边
graph_builder = StateGraph(State)
graph_builder.add_node("agent", chatbot)
graph_builder.add_node("tools", tool_node)

graph_builder.add_edge(START, "agent")
# 条件边：模型要调工具就去 tools，否则直接结束 —— 对应你手写的 if msg.tool_calls
graph_builder.add_conditional_edges("agent", tools_condition)
graph_builder.add_edge("tools", "agent")  # 工具执行完，回到 agent 继续思考（对应循环）

graph = graph_builder.compile()

def run(user_input):
    result = graph.invoke({"messages": [("user", user_input)]})
    return result["messages"][-1].content

if __name__ == "__main__":
    # 可选：把流程图打印/保存成结构，帮你直观理解
    try:
        png = graph.get_graph().draw_mermaid_png()
        with open("graph_structure.png", "wb") as f:
            f.write(png)
        print("流程图已存为 graph_structure.png")
    except Exception:
        pass

    while True:
        q = input("\n请交给我一个任务（q 退出）：").strip()
        if q.lower() == "q":
            break
        print("\n🤖", run(q))