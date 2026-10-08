from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import RemoveMessage
from langgraph.types import Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_core import build_graph, make_config
from database import SessionLocal, init_db
from models import Conversation, Message


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建业务表 + 打开 LangGraph 的 SQLite 现场
    await init_db()
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield


app = FastAPI(title="My Agent Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 请求模型 ----------
class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ResumeRequest(BaseModel):
    thread_id: str
    decision: str


# ---------- 工具函数 ----------
async def describe_state(graph, thread_id: str):
    """判断图是跑完了，还是停在 interrupt 等人批准"""
    state = await graph.aget_state(make_config(thread_id))
    if state.tasks and state.tasks[0].interrupts:
        return {
            "status": "waiting_approval",
            "approval": state.tasks[0].interrupts[0].value,
        }
    return {
        "status": "completed",
        "reply": state.values["messages"][-1].content,
    }


def unresolved_message_ids(messages) -> list[str]:
    """工具调用还没有对应结果时，返回从这条助手消息到末尾的 id。"""
    for index, message in enumerate(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            continue
        pending = {call["id"] for call in tool_calls}
        cursor = index + 1
        while cursor < len(messages) and getattr(messages[cursor], "type", None) == "tool":
            pending.discard(getattr(messages[cursor], "tool_call_id", None))
            cursor += 1
        if pending:
            return [item.id for item in messages[index:] if getattr(item, "id", None)]
    return []


async def prepare_thread(graph, thread_id: str):
    """还在等人审批时直接返回；工具结果缺失时先删掉这段坏掉的结尾。"""
    config = make_config(thread_id)
    state = await graph.aget_state(config)
    if state.tasks and state.tasks[0].interrupts:
        return {
            "status": "waiting_approval",
            "approval": state.tasks[0].interrupts[0].value,
        }
    remove_ids = unresolved_message_ids(state.values.get("messages") or [])
    if remove_ids:
        await graph.aupdate_state(
            config,
            {"messages": [RemoveMessage(id=message_id) for message_id in remove_ids]},
            as_node="agent",
        )
    return None


async def get_or_create_conversation(db: AsyncSession, thread_id: str) -> Conversation:
    result = await db.execute(
        select(Conversation).where(Conversation.thread_id == thread_id)
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        conv = Conversation(thread_id=thread_id)
        db.add(conv)
        await db.flush()  # 拿到 conv.id，供消息外键使用
    return conv

# 把这一轮已经跑完的助手回复写进 app.db 的 messages 表，供messages接口查询
async def save_assistant_reply(thread_id: str, content: str):
    async with SessionLocal() as db:
        conv = await get_or_create_conversation(db, thread_id)
        db.add(Message(conversation_id=conv.id, role="assistant", content=content))
        await db.commit()


# ---------- 路由 ----------
@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    graph = request.app.state.graph
    blocked = await prepare_thread(graph, req.thread_id)
    if blocked:
        return blocked

    # 1. 存用户消息
    async with SessionLocal() as db:
        conv = await get_or_create_conversation(db, req.thread_id)
        db.add(Message(conversation_id=conv.id, role="user", content=req.message))
        await db.commit()

    # 2. 跑 Agent
    await graph.ainvoke(
        {"messages": [("user", req.message)]},
        make_config(req.thread_id),
    )
    result = await describe_state(graph, req.thread_id)

    # 3. 只有真正跑完（不是暂停等批准）才存 AI 回复
    if result["status"] == "completed":
        await save_assistant_reply(req.thread_id, result["reply"])
    return result


@app.post("/chat/resume")
async def resume(req: ResumeRequest, request: Request):
    graph = request.app.state.graph

    await graph.ainvoke(Command(resume=req.decision), make_config(req.thread_id))
    result = await describe_state(graph, req.thread_id)

    if result["status"] == "completed":
        await save_assistant_reply(req.thread_id, result["reply"])
    return result


@app.get("/sessions/{thread_id}/messages")
async def get_messages(thread_id: str, page: int = 1, page_size: int = 20):
    async with SessionLocal() as db:
        conv = await get_or_create_conversation(db, thread_id)

        # 总数
        count_result = await db.execute(
            select(Message).where(Message.conversation_id == conv.id)
        )
        total = len(count_result.scalars().all())

        # 当前页（最新在前）
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = result.scalars().all()

    return {
        "thread_id": thread_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [
            {"role": m.role, "content": m.content, "created_at": str(m.created_at)}
            for m in reversed(rows)  # 展示时翻回时间正序
        ],
    }