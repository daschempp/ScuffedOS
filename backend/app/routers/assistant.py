"""Assistant chat endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from ..assistant import reply
from ..schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> dict:
    """Run the intent engine over the message and return a reply (+ optional action).

    Note: this endpoint is stateless. If the action carries `makeTask`, the client
    is responsible for POSTing to /api/tasks — so we never double-create here.
    """
    return reply(req.message)
