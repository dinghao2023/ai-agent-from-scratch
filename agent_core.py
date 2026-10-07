import os
from datetime import datetime
from dotenv import load_dotenv
from ddgs import DDGS

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
# from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt
from typing import Annotated
from typing_extensions import TypedDict

load_dotenv()

@tool
def calculator(expression: str) ->str:
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
    """联网搜索实时信息，新闻、最新事件时使用"""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "没有搜索到相关结果"
    return "\n\n".join(f"标题：{r['title']}\n摘要：{r['body']}" for r in results)

@tool
def send_email(to: str, subject: str, body: str) -> str:
    """发送邮件给指定收件人，参数为收件人地址、主题、正文。"""
    approval = interrupt({
        "question": f"确认发送邮件给 {to}？",
        "to": to, "subject": subject, "body": body,
    })
    if approval == "确认":
        return f"✅ 邮件已发送给 {to}"
    return "❌ 用户取消，邮件未发送"

tools = [calculator, get_current_time, web_search, send_email]

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
llm_with_tools = llm.bind_tools(tools)

class State(TypedDict):
    messages: Annotated[list, add_messages]

def chatbot(state: State):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

graph_builder = StateGraph(State)
graph_builder.add_node("agent", chatbot)
graph_builder.add_node("tools", ToolNode(tools))
graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", tools_condition)
graph_builder.add_edge("tools", "agent")

def build_graph(checkpointer):
    return graph_builder.compile(checkpointer=checkpointer)

def make_config(thread_id: str):
    return {"configurable": {"thread_id": thread_id}}