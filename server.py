from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import Command
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_core import build_graph, make_config

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时打开 SQLite 连接并编译 graph；服务关闭时自动释放连接
    async with AsyncSqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield

app = FastAPI(title="My Agent Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

class ChatRequest(BaseModel):
    thread_id: str
    message: str

class ResumeRequest(BaseModel):
    thread_id: str
    decision: str

async def describe_state(graph, thread_id: str):
    state = await graph.aget_state(make_config(thread_id))
    if state.tasks and state.tasks[0].interrupts:
        return {"status": "waiting_approval", "approval": state.tasks[0].interrupts[0].value}
    return {"status": "completed", "reply": state.values["messages"][-1].content}

@app.post("/chat")
async def chat(req: ChatRequest, request: Request):
    graph = request.app.state.graph
    await graph.ainvoke({"messages": [("user", req.message)]}, make_config(req.thread_id))
    return await describe_state(graph, req.thread_id)

@app.post("/chat/resume")
async def resume(req: ResumeRequest, request: Request):
    graph = request.app.state.graph
    await graph.ainvoke(Command(resume=req.decision), make_config(req.thread_id))
    return await describe_state(graph, req.thread_id)