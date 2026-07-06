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


# ---- email provider seam (M5) ---------------------------------------------
from app.providers.base import MoodleSnapshot, NormalizedEmail


class _FakeResponse:
    """Minimal httpx.Response stand-in: .status_code + .json()."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeGmailHTTP:
    """Scriptable transport for GoogleProvider.configure(fake_http=...).

    Routes GET by URL substring: '/messages/<id>' returns per-message JSON from
    `messages`; '/messages' (list) returns `{'messages': [{'id': ...}, ...]}`.
    A `status` override (keyed by url substring) forces an error status so the
    provider raises GoogleAuthError. Records every GET so tests can assert the
    label/maxResults query params reached Gmail.
    """

    def __init__(self, messages: dict | None = None, list_ids: list[str] | None = None,
                 status: dict | None = None, labels: list[dict] | None = None):
        self.messages = messages or {}          # id -> messages.get JSON
        self.list_ids = list_ids if list_ids is not None else list(self.messages)
        self.status = status or {}               # url-substring -> status_code
        self.labels = labels or []               # [{"id","name","type"}, ...]
        self.gets: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []

    def _status_for(self, url: str) -> int:
        for frag, code in self.status.items():
            if frag in url:
                return code
        return 200

    def get(self, url, headers=None, params=None):
        self.gets.append((url, dict(params or {})))
        code = self._status_for(url)
        if code >= 400:
            return _FakeResponse({}, code)
        if url.endswith("/labels"):
            return _FakeResponse({"labels": self.labels})
        # messages.get: '/messages/<id>' (has a segment after '/messages/')
        if "/messages/" in url:
            msg_id = url.rsplit("/messages/", 1)[1]
            return _FakeResponse(self.messages.get(msg_id, {}))
        # messages.list
        return _FakeResponse({"messages": [{"id": i} for i in self.list_ids]})

    def post(self, url, data=None, headers=None, json=None):
        """OAuth token/revoke calls use data=; Gmail write calls use json=.
        Routes by URL suffix: /messages/send -> a synthetic sent message id
        (echoing threadId if the caller supplied one so threading tests can
        assert it round-trips); /trash and /modify -> {} (Gmail returns the
        updated message, but callers here don't need the body); anything
        else (OAuth) -> {} as before."""
        self.posts.append((url, json if json is not None else data))
        code = self._status_for(url)
        if code >= 400:
            return _FakeResponse({}, code)
        if url.endswith("/messages/send"):
            body = json or {}
            return _FakeResponse({"id": "sent-1", "threadId": body.get("threadId")})
        if url.endswith("/trash") or url.endswith("/modify"):
            return _FakeResponse({})
        return _FakeResponse({})


def gmail_message(msg_id: str, *, thread_id: str = "t1", from_hdr: str,
                  subject: str, date_hdr: str, snippet: str = "",
                  label_ids: list[str] | None = None, body_text: str = "") -> dict:
    """Build a Gmail messages.get?format=full payload with a text/plain part."""
    import base64

    b64 = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": label_ids or [],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": from_hdr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date_hdr},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": b64}},
                {"mimeType": "text/html", "body": {"data": ""}},
            ],
        },
    }


# ---- moodle provider seam (M6) --------------------------------------------
class _Seq:
    """Wrap successive per-call responses for ONE wsfunction. Needed because a
    plain list is a LITERAL array payload (some Moodle WS functions —
    core_enrol_get_users_courses, mod_forum_get_forums_by_courses — return a
    top-level JSON array), so a list cannot also mean 'call sequence'. Use
    seq(...) ONLY for a wsfunction the provider calls more than once in one
    fetch (calendar pagination, per-course grades, per-assignment status,
    per-forum discussions). Exhausting a sequence keeps returning its last item."""

    def __init__(self, items):
        self.items = list(items)
        self.i = 0

    def next(self):
        item = self.items[min(self.i, len(self.items) - 1)]
        self.i += 1
        return item


def seq(*items):
    """seq(resp1, resp2, ...) — successive responses for a repeatedly-called wsfunction."""
    return _Seq(items)


class FakeMoodleHTTP:
    """Scriptable transport for MoodleProvider.configure(fake_http=...).

    Constructed with responses= (alias: payloads=), a dict wsfunction -> value:
      - a dict OR list value is returned LITERALLY every call (a list is a real
        top-level array payload, e.g. core_enrol_get_users_courses returns a
        JSON array of courses);
      - a seq(...) value pops the next scripted response per successive call.
    exceptions= maps wsfunction -> an exception dict {"exception","errorcode",
    "message"} (Moodle returns errors as HTTP 200 with an "exception" key — see
    contract §C). .post(url, data=...) routes on data["wsfunction"] and records
    every post as (url, flattened-form-dict) so tests can assert the params
    reached server.php.
    """

    def __init__(self, responses: dict | None = None, exceptions: dict | None = None,
                 payloads: dict | None = None):
        # payloads= is a back-compat alias for responses=.
        self.responses = dict(responses if responses is not None else (payloads or {}))
        self.exceptions = exceptions or {}
        self.posts: list[tuple[str, dict]] = []  # (url, form-data dict)

    def post(self, url, data=None, headers=None):
        data = dict(data or {})
        self.posts.append((url, data))
        fn = data.get("wsfunction", "")
        if fn in self.exceptions:
            # Moodle web-service error: HTTP 200 with an exception body.
            return _FakeResponse(dict(self.exceptions[fn]))
        value = self.responses.get(fn, {})
        if isinstance(value, _Seq):
            return _FakeResponse(value.next())
        return _FakeResponse(value)     # literal dict OR top-level array

    def get(self, url, headers=None, params=None):  # unused by MoodleProvider
        return _FakeResponse({})


class FakeEmailProvider:
    """Scriptable EmailProvider stand-in (name='google') — no network.

    Installed via ``providers.configure([FakeEmailProvider(...)])``. Satisfies the
    new EmailProvider protocol so the shared oauth router and email_sync accept it.
    """

    name = "google"

    def __init__(
        self,
        *,
        tokens: Tokens | None = None,
        messages: list[NormalizedEmail] | None = None,
        body: str = "Full body text.",
        raise_auth: bool = False,
    ) -> None:
        self.tokens = tokens or Tokens(
            access_token="g-access", refresh_token="g-refresh", expires_at=None,
            scopes="openid email https://www.googleapis.com/auth/gmail.readonly",
            provider_user_id="google-sub-1",
        )
        self.messages = messages or []
        self.body = body
        self.raise_auth = raise_auth
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []
        self.injected: list[Tokens | None] = []
        self.fetched_since: list = []
        self.fetched_bodies: list[str] = []

    # ---- OAuthProvider ----
    def set_tokens(self, tokens):
        self.injected.append(tokens)

    def authorize_url(self, state: str) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id=fake-google&response_type=code&state={state}"
        )

    def exchange_code(self, code: str) -> Tokens:
        self.exchanged.append(code)
        return self.tokens

    def refresh(self, tokens: Tokens) -> Tokens:
        self.refreshed.append(tokens)
        return self.tokens

    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)

    def fetch_profile(self, tokens: Tokens) -> str | None:
        return "google-sub-1"

    def success_redirect(self) -> str:
        return "/?screen=email&connected=google"

    def on_connected(self) -> None:
        from app import email_sync

        email_sync.tick()

    def on_disconnect(self) -> None:
        from app.store import store

        store.delete_email_data(self.name)

    # ---- EmailProvider ----
    def fetch_messages(self, since):
        from app.providers.google import GoogleAuthError

        if self.raise_auth:
            raise GoogleAuthError("gmail 401")
        self.fetched_since.append(since)
        return list(self.messages)

    def get_message(self, source_id: str) -> str:
        self.fetched_bodies.append(source_id)
        return self.body


class FakeMoodleProvider:
    """Scriptable MoodleProvider stand-in (name='moodle') — no network.

    Installed via ``providers.configure([FakeMoodleProvider(...)])``. Satisfies the
    MoodleProvider protocol (contract §B/§C) so the shared oauth router and
    moodle_sync accept it. Its distinguishing method is fetch_school_snapshot —
    moodle_sync selects providers by hasattr on it, exactly as email_sync selects
    by hasattr(p, 'fetch_messages'). Records every OAuth call so router tests can
    assert exchange/refresh/revoke ran; raise_auth drives the needs_reauth path.
    """

    name = "moodle"

    def __init__(
        self,
        *,
        tokens: Tokens | None = None,
        snapshot: MoodleSnapshot | None = None,
        site_info: dict | None = None,
        raise_auth: bool = False,
    ) -> None:
        self.tokens = tokens or Tokens(
            access_token="m-wstoken", refresh_token=None, expires_at=None,
            scopes="", provider_user_id="42",
        )
        self.snapshot = snapshot or MoodleSnapshot()
        self.site_info = site_info or {
            "userid": 42, "sitename": "WolfWare", "release": "5.2",
            "functions": [],
        }
        self.raise_auth = raise_auth
        self.exchanged: list[str] = []
        self.refreshed: list[Tokens] = []
        self.revoked: list[Tokens] = []
        self.injected: list[Tokens | None] = []
        self.fetched_since: list = []
        self.site_info_calls: list[str] = []

    # ---- OAuthProvider ----
    def set_tokens(self, tokens):
        self.injected.append(tokens)

    def authorize_url(self, state: str) -> str:
        return (
            "https://moodle-courses2527.wolfware.ncsu.edu/admin/tool/mobile/launch.php"
            f"?service=moodle_mobile_app&state={state}"
        )

    def exchange_code(self, code: str) -> Tokens:
        self.exchanged.append(code)
        return self.tokens

    def refresh(self, tokens: Tokens) -> Tokens:
        # Moodle has no refresh endpoint — passthrough (contract §C).
        self.refreshed.append(tokens)
        return tokens

    def revoke(self, tokens: Tokens) -> None:
        self.revoked.append(tokens)

    def success_redirect(self) -> str:
        return "/?screen=school&connected=moodle"

    def on_connected(self) -> None:
        from app import moodle_sync

        moodle_sync.tick()

    def on_disconnect(self) -> None:
        from app.store import store

        store.delete_moodle_data(self.name)

    # ---- MoodleProvider ----
    def get_site_info(self, token: str) -> dict:
        self.site_info_calls.append(token)
        return self.site_info

    def fetch_school_snapshot(self, since):
        from app.providers.moodle import MoodleAuthError

        if self.raise_auth:
            raise MoodleAuthError("moodle invalidtoken")
        self.fetched_since.append(since)
        return self.snapshot


# ---- plaid provider seam (M7) ---------------------------------------------
class FakePlaidHTTP:
    """Scriptable transport for PlaidProvider.configure(fake_http=...).

    Routes .post(url, json=...) by URL-path substring. `responses` maps a path
    fragment (e.g. '/accounts/get') to a JSON dict (or seq(...) for repeated
    calls, e.g. paginated /transactions/sync). `status` maps a fragment to an
    error status_code; when >=400 the matching `responses` body (a Plaid
    {error_code, error_message} dict) is returned so the provider maps it to
    PlaidAuthError/PlaidError. Records every post as (url, json-body)."""

    def __init__(self, responses: dict | None = None, status: dict | None = None):
        self.responses = dict(responses or {})
        self.status = dict(status or {})
        self.posts: list[tuple[str, dict]] = []

    def _match(self, url: str, table: dict):
        for frag, val in table.items():
            if frag in url:
                return val
        return None

    def post(self, url, json=None, headers=None):
        self.posts.append((url, dict(json or {})))
        code = self._match(url, self.status) or 200
        val = self._match(url, self.responses)
        if code >= 400:
            body = val if isinstance(val, dict) else {
                "error_code": "INVALID_ACCESS_TOKEN", "error_message": "bad token"}
            return _FakeResponse(body, code)
        if isinstance(val, _Seq):
            return _FakeResponse(val.next())
        return _FakeResponse(val if val is not None else {})

    def get(self, url, headers=None, params=None):   # unused by PlaidProvider
        return _FakeResponse({})
