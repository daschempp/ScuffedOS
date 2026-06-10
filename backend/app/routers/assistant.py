"""Assistant endpoints: chat (JSON + SSE streaming) and conversation resume."""
from __future__ import annotations

import json
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import assistant, llm
from ..schemas import ChatRequest, ChatResponse, ConversationOut
from ..store import store

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _require_llm() -> None:
    if not llm.available():
        raise HTTPException(
            status_code=503,
            detail="Assistant is offline — set ANTHROPIC_API_KEY in backend/.env.",
        )


def _capture_async(message: str, text: str) -> None:
    threading.Thread(
        target=assistant.capture, args=(message, 0, text), daemon=True
    ).start()


def _llm_failure_detail(exc: Exception) -> str:
    """A truthful, user-facing reason the assistant couldn't answer
    (billing/auth/rate-limit problems shouldn't masquerade as a 500)."""
    return f"Assistant is unavailable: {exc}"


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> dict:
    _require_llm()
    import anthropic

    try:
        payload = assistant.reply(req.message, req.conversation_id)
    except anthropic.APIError as exc:
        raise HTTPException(status_code=503, detail=_llm_failure_detail(exc))
    _capture_async(req.message, payload["text"])
    return payload


@router.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-sent events: meta → delta* → (tool/action)* → done.
    Failures mid-stream arrive as an `error` event (the status is already 200)."""
    _require_llm()

    def sse():
        final_text = ""
        try:
            for event, data in assistant.run_turn(req.message, req.conversation_id):
                if event == "done":
                    final_text = data["text"]
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
        except Exception as exc:  # surface, don't sever — client falls back
            yield f"event: error\ndata: {json.dumps({'message': _llm_failure_detail(exc)})}\n\n"
            return
        if final_text:
            _capture_async(req.message, final_text)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversation", response_model=ConversationOut | None)
def latest_conversation() -> dict | None:
    """The most recent conversation with its messages — chat history survives
    backend restarts (M2 acceptance)."""
    conv = store.latest_conversation()
    if conv is None:
        return None
    return {
        "id": conv["id"],
        "title": conv["title"],
        "messages": store.list_messages(conv["id"]),
    }
