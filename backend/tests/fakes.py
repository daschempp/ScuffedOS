"""Scriptable stand-ins for the LLM seam and the Mem0 engine."""
from __future__ import annotations

from types import SimpleNamespace


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(name: str, input: dict, block_id: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=input, id=block_id)


def text_turn(text: str) -> SimpleNamespace:
    """A model response that just answers (ends the loop)."""
    return SimpleNamespace(stop_reason="end_turn", content=[text_block(text)])


def tool_turn(*blocks: SimpleNamespace, preamble: str = "") -> SimpleNamespace:
    """A model response requesting tool calls (optionally with leading text)."""
    content = ([text_block(preamble)] if preamble else []) + list(blocks)
    return SimpleNamespace(stop_reason="tool_use", content=content)


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        for block in self._message.content:
            if block.type == "text" and block.text:
                # Split so streaming consumers see multiple deltas.
                mid = max(1, len(block.text) // 2)
                yield block.text[:mid]
                yield block.text[mid:]

    def get_final_message(self):
        return self._message


class FakeLLM:
    """Plays back a script of turns; records every request it was sent."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if not self.turns:
            raise AssertionError("FakeLLM script exhausted")
        return _FakeStream(self.turns.pop(0))


class FakeMem0:
    """Mimics mem0.Memory: scripted add() events, recorded mutations."""

    def __init__(self, add_results=None, search_results=None):
        self.add_results = list(add_results or [])
        self.search_results = search_results or []
        self.added: list = []
        self.updated: list = []
        self.deleted: list = []

    def add(self, messages, **kwargs):
        self.added.append((messages, kwargs))
        results = self.add_results.pop(0) if self.add_results else []
        return {"results": results}

    def search(self, query, **kwargs):
        return {"results": self.search_results}

    def update(self, memory_id, data, **kwargs):
        self.updated.append((memory_id, data))

    def delete(self, memory_id):
        self.deleted.append(memory_id)


# ---- fitness provider seam (M4) -------------------------------------------
from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens


class FakeProvider:
    """Scriptable stand-in for WhoopProvider — no network.

    Installed with ``providers.configure([FakeProvider()])``. Records the
    calls the OAuth router makes so tests can assert exchange/revoke ran.
    """

    name = "whoop"
    kind = "pull"

    def __init__(
        self,
        *,
        tokens: Tokens | None = None,
        snapshots: list[NormalizedSnapshot] | None = None,
        workouts: list[NormalizedWorkout] | None = None,
    ) -> None:
        self.tokens = tokens or Tokens(
            access_token="fake-access",
            refresh_token="fake-refresh",
            expires_at=None,
            scopes="read:recovery read:workout",
            provider_user_id="whoop-user-1",
        )
        self.snapshots = snapshots or []
        self.workouts = workouts or []
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []
        self.connected_calls = 0

    def authorize_url(self, state: str) -> str:
        return (
            "https://api.prod.whoop.com/oauth/oauth2/auth"
            f"?client_id=fake-client&response_type=code&state={state}"
        )

    def exchange_code(self, code: str) -> Tokens:
        self.exchanged.append(code)
        return self.tokens

    def refresh(self, tokens: Tokens) -> Tokens:
        self.refreshed.append(tokens)
        return self.tokens

    def fetch_recovery(self, since):
        return list(self.snapshots)

    def fetch_sleep(self, since):
        return []

    def fetch_workouts(self, since):
        return list(self.workouts)

    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)

    # ---- OAuthProvider hooks (M5) — the shared oauth router drives these ----
    def success_redirect(self) -> str:
        return "/?screen=fitness&connected=whoop"

    def on_connected(self) -> None:
        self.connected_calls = getattr(self, "connected_calls", 0) + 1
        # Mirror WhoopProvider: kick an immediate sync so the callback test's
        # tick-count assertion (len(ticks) == 1) passes against either the
        # old fitness callback or the new shared oauth callback.
        from app import fitness_sync  # noqa: PLC0415
        fitness_sync.tick()

    def on_disconnect(self) -> None:
        # Mirror the real provider: delete this provider's normalized data.
        # Idempotent with the router's own delete_provider_data (row gone).
        from app.store import store
        store.delete_provider_data(self.name)
