import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.types import Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_core import build_graph, make_config
from database import SessionLocal, init_db
from models import Conversation, Message
from deps import verify_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent-service")


# ---------- 生命周期 ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("服务启动，初始化数据库")
    await init_db()
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield
    logger.info("服务关闭")


app = FastAPI(title="My Agent Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 全局异常兜底 ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


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


async def save_assistant_reply(thread_id: str, content: str):
    async with SessionLocal() as db:
        conv = await get_or_create_conversation(db, thread_id)
        db.add(Message(conversation_id=conv.id, role="assistant", content=content))
        await db.commit()


# ---------- 路由（都挂了鉴权）----------
@app.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    graph = request.app.state.graph

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

    # 3. 跑完（非暂停）才存 AI 回复
    if result["status"] == "completed":
        await save_assistant_reply(req.thread_id, result["reply"])
    return result


@app.post("/chat/resume")
async def resume(
    req: ResumeRequest,
    request: Request,
    _key: str = Depends(verify_api_key),
):
    graph = request.app.state.graph

    await graph.ainvoke(Command(resume=req.decision), make_config(req.thread_id))
    result = await describe_state(graph, req.thread_id)

    if result["status"] == "completed":
        await save_assistant_reply(req.thread_id, result["reply"])
    return result


@app.get("/sessions/{thread_id}/messages")
async def get_messages(
    thread_id: str,
    page: int = 1,
    page_size: int = 20,
    _key: str = Depends(verify_api_key),
):
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