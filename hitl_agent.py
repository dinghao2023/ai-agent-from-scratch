import os
from datetime import datetime
from dotenv import load_dotenv
from ddgs import DDGS

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from typing import Annotated
from typing_extensions import TypedDict
from rich import print as rprint

load_dotenv()

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
    """联网搜索实时信息，新闻、最新事件时使用"""
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=5))
    if not results:
        return "没有搜索到相关结果"
    return "\n\n".join(f"标题：{r['title']}\n摘要：{r['body']}" for r in results)

# 新增：模拟"发邮件"这种敏感操作 —— 必须等人确认
@tool
def send_email(to: str, subject: str, body: str) -> str:
    """发送邮件给指定收件人，参数为收件人地址、主题、正文。"""
    # interrupt：走到这，图会暂停，把问题抛给人类，等人回复后才往下走
    approval = interrupt({
        "question": f"确认发送邮件给 {to}？\n主题：{subject}\n正文：{body}",
        "to": to,
        "subject": subject,
    })
    if approval == "确认":
        # 真实项目这里才调真正的发信接口；现在模拟
        return f"✅ 邮件已发送给 {to}"
    return "❌ 用户取消，邮件未发送"

tools = [calculator, get_current_time, web_search, send_email]

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
llm_with_tools = llm.bind_tools(tools)

# 只在一个线程的第一轮放进状态；之后的用户消息由 chat() 追加
SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "你是一个工具调用助手。规则："
        "1）用户要求发送邮件时，必须直接调用 send_email 工具，严禁自己用文字询问确认或模拟发送；"
        "2）需要最新信息用 web_search，计算用 calculator，获取时间用 get_current_time；"
        "3）只在工具返回结果后才组织最终回答。"
    ),
}

class State(TypedDict):
    messages: Annotated[list, add_messages]

def chatbot(state: State):
    msg = llm_with_tools.invoke(state["messages"])
    # rprint("msg:", msg)
    return {"messages": [msg]}

tool_node = ToolNode(tools)

graph_builder = StateGraph(State)
graph_builder.add_node("agent", chatbot)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", tools_condition)
graph_builder.add_edge("tools", "agent")

# 关键①：挂上 checkpointer，图从此能"记住线程 + 暂停恢复"
checkpointer = InMemorySaver()
graph = graph_builder.compile(checkpointer=checkpointer)

# 用 thread_id 标识一个独立对话（就像 P0 的 session_id）
config = {"configurable": {"thread_id": "thread-1"}}

def chat(user_input):
    messages = [("user", user_input)]
    existing = (graph.get_state(config).values or {}).get("messages")
    if not existing:
        messages = [SYSTEM_MESSAGE, *messages]
    return graph.invoke({"messages": messages}, config)

def settle(result):
    """图停在 interrupt 时就地询问，并用 Command(resume=...) 从暂停处继续。"""
    while True:
        pending = graph.get_state(config).interrupts
        if not pending:
            return result
        payload = pending[0].value
        question = payload["question"] if isinstance(payload, dict) else str(payload)
        print("\n⏸️ Agent 请求确认：")
        print(question)
        decision = input("回复「确认」发送，其他任意内容取消：").strip()
        result = graph.invoke(Command(resume=decision), config)

if __name__ == "__main__":
    print("试试让我：发一封邮件 / 查新闻 / 算数")
    while True:
        q = input("\n你：").strip()
        if q.lower() == "q":
            break

        result = settle(chat(q))
        print("\n🤖", result["messages"][-1].content)