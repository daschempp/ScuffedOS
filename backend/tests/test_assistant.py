"""The real assistant: tool loop, persistence, streaming, availability."""
import json

from app import llm
from app.store import store

from .fakes import FakeLLM, text_turn, tool_block, tool_turn


def chat(client, message: str, conversation_id=None) -> dict:
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    res = client.post("/api/assistant/chat", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_chat_returns_503_without_api_key(client):
    res = client.post("/api/assistant/chat", json={"message": "hello"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "service_unavailable"


def test_tool_call_creates_a_real_task(client):
    """M2 acceptance: 'add a task to call mom' creates a task via tool call."""
    llm.configure(FakeLLM(
        tool_turn(tool_block("create_task", {"label": "Call mom", "list": "Personal"})),
        text_turn("Done — added Call mom to your tasks."),
    ))
    body = chat(client, "add a task to call mom")

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 1 and tasks[0]["label"] == "Call mom"
    assert body["text"] == "Done — added Call mom to your tasks."
    assert body["actions"][0]["screen"] == "tasks"
    assert body["actions"][0]["title"] == "Added to Tasks"


def test_tool_results_are_fed_back_to_the_model(client):
    fake = FakeLLM(
        tool_turn(tool_block("list_tasks", {})),
        text_turn("You have nothing open."),
    )
    llm.configure(fake)
    chat(client, "what's on my plate?")

    assert len(fake.calls) == 2
    followup = fake.calls[1]["messages"]
    assert followup[-1]["role"] == "user"
    result = followup[-1]["content"][0]
    assert result["type"] == "tool_result"
    assert json.loads(result["content"]) == {"tasks": []}


def test_conversation_persists_and_resumes(client):
    llm.configure(FakeLLM(text_turn("Hi!"), text_turn("Still here.")))
    first = chat(client, "hello")
    conv_id = first["conversation_id"]
    second = chat(client, "you there?", conversation_id=conv_id)
    assert second["conversation_id"] == conv_id

    # Rows are durable — exactly what a backend restart would replay.
    messages = store.list_messages(conv_id)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "hello"

    res = client.get("/api/assistant/conversation").json()
    assert res["id"] == conv_id
    assert res["title"] == "hello"
    assert len(res["messages"]) == 4


def test_history_is_sent_back_to_the_model(client):
    fake = FakeLLM(text_turn("Hi!"), text_turn("Yes."))
    llm.configure(fake)
    first = chat(client, "remember the plan?")
    chat(client, "good", conversation_id=first["conversation_id"])

    history = fake.calls[1]["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[0]["content"] == "remember the plan?"


def test_unknown_conversation_id_starts_fresh(client):
    llm.configure(FakeLLM(text_turn("Hi!")))
    body = chat(client, "hello", conversation_id=999)
    assert body["conversation_id"] != 999


def test_assistant_message_records_actions(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("create_task", {"label": "Pay rent"})),
        text_turn("Added."),
    ))
    body = chat(client, "add a task to pay rent")
    messages = store.list_messages(body["conversation_id"])
    assert messages[-1]["actions"][0]["title"] == "Added to Tasks"


def test_streaming_endpoint_emits_sse_events(client):
    llm.configure(FakeLLM(
        tool_turn(tool_block("create_task", {"label": "Call mom"})),
        text_turn("Done — added it."),
    ))
    with client.stream("POST", "/api/assistant/chat/stream",
                       json={"message": "add a task to call mom"}) as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        raw = "".join(res.iter_text())

    events = []
    for chunk in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))

    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and "conversation_id" in events[0][1]
    assert "tool" in kinds and "action" in kinds and "delta" in kinds
    assert kinds[-1] == "done"
    done = events[-1][1]
    assert done["text"] == "Done — added it."
    assert done["actions"][0]["screen"] == "tasks"
    # And the streamed turn persisted like any other.
    assert len(store.list_messages(done["conversation_id"])) == 2


def test_streaming_endpoint_503_without_api_key(client):
    res = client.post("/api/assistant/chat/stream", json={"message": "hi"})
    assert res.status_code == 503


def test_streaming_failures_surface_as_error_events(client):
    llm.configure(FakeLLM())  # empty script — first stream call raises
    with client.stream("POST", "/api/assistant/chat/stream",
                       json={"message": "hi"}) as res:
        raw = "".join(res.iter_text())
    assert "event: error" in raw
    assert "Assistant is unavailable" in raw


def test_tool_errors_go_back_to_the_model_not_the_user(client):
    fake = FakeLLM(
        tool_turn(tool_block("update_task", {"task_id": 12345, "done": True})),
        text_turn("Hmm, I couldn't find that task."),
    )
    llm.configure(fake)
    body = chat(client, "complete task 12345")
    assert body["actions"] == []
    result = json.loads(fake.calls[1]["messages"][-1]["content"][0]["content"])
    assert "error" in result


def test_model_routing_escalates_heavy_work():
    assert llm.pick_model("plan my day") == "claude-opus-4-8"
    assert llm.pick_model("add a task to call mom") == "claude-haiku-4-5"


def test_empty_message_is_rejected(client):
    llm.configure(FakeLLM())
    res = client.post("/api/assistant/chat", json={"message": ""})
    assert res.status_code == 422
