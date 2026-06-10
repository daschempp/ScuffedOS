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
