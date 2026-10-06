from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langgraph.types import Command

from agent_core import graph, make_config

app = FastAPI(title="My Agent Service")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

class ChatRequest(BaseModel):
    thread_id: str
    message: str

class ResumeRequest(BaseModel):
    thread_id: str
    decision: str  # "确认" 或其他

def describe_state(thread_id: str):
    """看当前图是跑完了，还是停在 interrupt 等人"""
    state = graph.get_state(make_config(thread_id))
    if state.tasks and state.tasks[0].interrupts:
        payload = state.tasks[0].interrupts[0].value
        return {"status": "waiting_approval", "approval": payload}
    return {"status": "completed", "reply": state.values["messages"][-1].content}

@app.post("/chat")
async def chat(req: ChatRequest):
    await graph.ainvoke(
        {"messages": [("user", req.message)]}, make_config(req.thread_id)
    )
    return describe_state(req.thread_id)

@app.post("/chat/resume")
async def resume(req: ResumeRequest):
    await graph.ainvoke(Command(resume=req.decision), make_config(req.thread_id))
    return describe_state(req.thread_id)