"""Mem0 integration: auto-capture mirroring, verbatim filing, sync, fallback."""
import os

from app import llm, memory_engine
from app.store import store

from .fakes import FakeLLM, FakeMem0, text_turn, tool_block, tool_turn


def test_capture_turn_mirrors_add_update_delete():
    fake = FakeMem0(add_results=[[
        {"event": "ADD", "id": "m0-1", "memory": "Prefers morning workouts"},
    ]])
    memory_engine.configure(fake)
    memory_engine.capture_turn("I like working out in the morning", "Noted!")

    rows = store.list_memories()
    assert len(rows) == 1
    assert rows[0]["text"] == "Prefers morning workouts"
    assert rows[0]["src"] == "learned"

    # A later exchange revises and then retracts the same fact.
    fake.add_results = [[
        {"event": "UPDATE", "id": "m0-1", "memory": "Prefers evening workouts now"},
    ]]
    memory_engine.capture_turn("actually I work out at night now", "Updated.")
    assert store.list_memories()[0]["text"] == "Prefers evening workouts now"

    fake.add_results = [[{"event": "DELETE", "id": "m0-1"}]]
    memory_engine.capture_turn("forget my workout preference", "Done.")
    assert store.list_memories() == []


def test_capture_infers_with_mem0(client):
    fake = FakeMem0(add_results=[[]])
    memory_engine.configure(fake)
    memory_engine.capture_turn("hello", "hi")
    messages, kwargs = fake.added[0]
    assert kwargs["infer"] is True
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_remember_tool_files_verbatim(client):
    """Explicit 'remember X' bypasses inference (infer=False) and is stored
    word-for-word, even while auto-capture stays on."""
    fake = FakeMem0(add_results=[[{"event": "ADD", "id": "m0-9", "memory": "Passport in the blue box"}]])
    memory_engine.configure(fake)
    llm.configure(FakeLLM(
        tool_turn(tool_block("remember", {"text": "Passport in the blue box"})),
        text_turn("Saved."),
    ))
    res = client.post("/api/assistant/chat", json={"message": "remember the passport is in the blue box"})
    assert res.status_code == 200
    assert res.json()["actions"][0]["screen"] == "memory"

    _messages, kwargs = fake.added[0]
    assert kwargs["infer"] is False
    row = store.list_memories()[0]
    assert row["text"] == "Passport in the blue box"
    assert row["mem0_id"] == "m0-9"


def test_api_created_memory_is_indexed_and_synced(client):
    fake = FakeMem0(add_results=[[{"event": "ADD", "id": "m0-5", "memory": "Gym closes at 10"}]])
    memory_engine.configure(fake)

    created = client.post("/api/memory", json={"text": "Gym closes at 10"}).json()
    assert store.list_memories()[0]["mem0_id"] == "m0-5"

    client.patch(f"/api/memory/{created['id']}", json={"text": "Gym closes at 11"})
    assert fake.updated == [("m0-5", "Gym closes at 11")]

    client.delete(f"/api/memory/{created['id']}")
    assert fake.deleted == ["m0-5"]


def test_search_returns_scored_hits():
    memory_engine.configure(FakeMem0(search_results=[
        {"id": "m0-1", "memory": "Mom's birthday is March 14", "score": 0.91},
    ]))
    hits = memory_engine.search("when is mom's birthday?")
    assert hits == [{"id": "m0-1", "text": "Mom's birthday is March 14", "score": 0.91}]


def test_everything_degrades_when_engine_offline(client):
    """Chat, notes and the search tool all keep working without Mem0."""
    assert memory_engine.search("anything") is None

    row = memory_engine.remember_verbatim("Still works offline")
    assert row["text"] == "Still works offline"
    assert store.list_memories()[0]["mem0_id"] is None

    llm.configure(FakeLLM(
        tool_turn(tool_block("search_memory", {"query": "birthday"})),
        text_turn("Here's what I have."),
    ))
    res = client.post("/api/assistant/chat", json={"message": "when is mom's birthday?"})
    assert res.status_code == 200


def test_recalled_memories_enter_the_system_prompt(client):
    memory_engine.configure(FakeMem0(search_results=[
        {"id": "m0-1", "memory": "Mom's birthday is March 14", "score": 0.9},
    ]))
    fake = FakeLLM(text_turn("It's March 14."))
    llm.configure(fake)
    client.post("/api/assistant/chat", json={"message": "when is mom's birthday?"})
    assert "Mom's birthday is March 14" in fake.calls[0]["system"]


def test_lazy_init_opts_out_of_mem0_telemetry(monkeypatch):
    """mem0's telemetry module reads MEM0_TELEMETRY at import time and defaults it
    ON (PostHog). The privacy policy promises no third-party analytics, so the
    opt-out has to be in place *before* the import — assert it on the real lazy
    path, which `configure()` normally short-circuits."""
    import sys
    import types

    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)
    monkeypatch.setattr(memory_engine.settings, "memory_enabled", True)
    monkeypatch.setattr(memory_engine.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(memory_engine.settings, "openai_api_key", "sk-oai-test")
    monkeypatch.setattr(memory_engine.settings, "database_url", "postgresql+psycopg://x/y")

    seen: dict[str, str | None] = {}

    class _FakeMemory:
        @staticmethod
        def from_config(_cfg):
            # Sampled at the moment mem0 would be imported for real.
            seen["telemetry"] = os.environ.get("MEM0_TELEMETRY")
            return FakeMem0(add_results=[[]])

    monkeypatch.setitem(sys.modules, "mem0",
                        types.SimpleNamespace(Memory=_FakeMemory))

    memory_engine.configure("unset")          # take the real lazy path
    try:
        assert memory_engine._get() is not None
        assert seen["telemetry"] == "False"
    finally:
        memory_engine.configure(None)
