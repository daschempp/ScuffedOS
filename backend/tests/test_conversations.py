"""Store-level coverage for conversations — the M2 assistant builds on these."""
from app.store import store


def test_conversation_roundtrip():
    conv = store.create_conversation()
    assert conv["id"] and conv["title"] is None

    store.add_message(conv["id"], "user", "add a task to call mom")
    store.add_message(conv["id"], "assistant", "Done — added it.",
                      actions=[{"title": "Added to Tasks", "screen": "tasks"}])

    messages = store.list_messages(conv["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "add a task to call mom"
    assert messages[1]["actions"][0]["screen"] == "tasks"


def test_first_user_message_titles_the_conversation():
    conv = store.create_conversation()
    store.add_message(conv["id"], "user", "plan my day")
    assert store.get_conversation(conv["id"])["title"] == "plan my day"


def test_latest_conversation_tracks_activity():
    first = store.create_conversation()
    second = store.create_conversation()
    assert store.latest_conversation()["id"] == second["id"]
    # activity bumps a conversation back to the top
    store.add_message(first["id"], "user", "hello again")
    assert store.latest_conversation()["id"] == first["id"]


def test_add_message_to_unknown_conversation_returns_none():
    assert store.add_message(999, "user", "hello") is None


def test_latest_conversation_empty_db():
    assert store.latest_conversation() is None
