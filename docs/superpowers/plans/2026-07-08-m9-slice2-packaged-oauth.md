# M9 Slice 2 — Packaged OAuth Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

Goal: Make Google OAuth and Plaid Hosted Link work inside the packaged (unsigned) ScuffedOS .app by driving consent through the user's real system browser + a runtime-computed loopback redirect + PKCE. The dev consent flow (webview new-tab) is preserved; two intentional dev-side changes: (1) Task 8's post-connect auto-poll also runs in dev, a harmless auto-refresh that flips the card without a manual refresh; (2) the dev Google redirect default flips from `localhost:8000` to `127.0.0.1:8000` (empty `google_redirect_uri` → computed loopback) — see the "Dev-side change to disclose (M2)" note in the live-gate section for the dev-`.env`/Desktop-client implication.

Architecture: The Tauri shell exports the sidecar's random port as `SCUFFEDOS_PORT`; `config.py` binds it to a new `scuffedos_port` field, and `GoogleProvider` computes `http://127.0.0.1:{scuffedos_port}/auth/google/callback` at request time whenever `google_redirect_uri` is empty. The shared OAuth router owns a PKCE (S256) flow — it mints a verifier at connect time, stores `_STATES[state] = (provider, verifier)`, passes a `code_challenge` into `authorize_url`, and rides the verifier back into `exchange_code` at callback; only Google consumes them. The frontend routes Connect/Plaid-link through the Tauri opener plugin under `isTauri()` and polls `GET /api/connectors` for the post-consent flip.

Tech Stack: Python 3.14 / FastAPI / pydantic-settings (backend, pytest via `../.venv/bin/python -m pytest`); React + Vite (frontend, verified by `npm run build` only); Rust / Tauri v2 (`src-tauri/`, verified by `cargo check`).

## Global Constraints

- Baseline suite is 687 passed / 1 skipped; keep the suite green and report the pass count after every backend task (house rule). Each backend task below states BOTH the delta (`+N new`) and the resulting absolute so the arithmetic is self-checking against the 687 baseline. If your local baseline differs, trust the delta and re-pin the absolute — run `cd backend && ../.venv/bin/python -m pytest -q` before Task 1 to confirm 687/1.
- NO new tables / NO migration / alembic head stays 0009 — Slice 2 adds only a Settings field, two protocol-signature extensions, and the `_STATES` tuple value.
- Tests stay hermetic through the existing seams (`providers.configure([fakes])`, `no_external_services` autouse fixture, `monkeypatch`/env dict, TestClient) — zero network.
- Frontend is verified by `npm run build` from `frontend/` ONLY; do NOT introduce a frontend test harness (§14).
- The config field name is `scuffedos_port` NOT `backend_port`, and it binds `SCUFFEDOS_PORT` (pydantic default name↔env binding; no `env_prefix`/alias — mirrors the `scuffedos_managed_pg` ↔ `SCUFFEDOS_MANAGED_PG` precedent).
- The coordinated `exchange_code`/`authorize_url` protocol signature change must land so the suite is NEVER red across a commit boundary (widen every impl + fake + inline-test-fake in the SAME commit, params optional with default `None`).
- Deep-link / custom scheme / code-signing / notarization / the WHOOP bounce page are SLICE 3 — OUT OF SCOPE here.
- Reuse the existing `google_client_id` / `google_client_secret` fields for the GCP "Desktop app" client (the user swaps the client type in GCP and re-pastes the same two keys in the API-keys tab) — NO new Settings fields and NO new `SECRET_FIELD_MAP` entries are needed for Slice 2. (Resolves the config verifier's Desktop-client open question.)

---

### Task 1: config — add `scuffedos_port` field bound to `SCUFFEDOS_PORT`

Files:
- Modify: `backend/app/config.py` (insert a field into the M8 managed-PG block, currently lines 121–130; the field sits next to `scuffedos_managed_pg` at line 126)
- Test: `backend/tests/test_ship_config.py` (add two tests next to `test_managed_pg_reads_env` at lines 25–28)

Interfaces:
- Produces: `Settings.scuffedos_port: int` (default `8000`, env `SCUFFEDOS_PORT`), consumed later by `GoogleProvider` (Task 2) and set by the Tauri shell (Task 5).

Steps:

- [ ] Write the failing tests. Append to `backend/tests/test_ship_config.py`:
```python
def test_scuffedos_port_reads_env(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_PORT", "4300")
    fresh = Settings()
    assert fresh.scuffedos_port == 4300


def test_scuffedos_port_defaults_to_8000():
    assert Settings.model_fields["scuffedos_port"].default == 8000
```
- [ ] Run it, confirm FAIL. `cd backend && ../.venv/bin/python -m pytest tests/test_ship_config.py -q` → expected FAIL: `AttributeError: 'Settings' object has no attribute 'scuffedos_port'` (and the `model_fields["scuffedos_port"]` KeyError).
- [ ] Minimal implementation. In `backend/app/config.py`, add the field immediately after `scuffedos_managed_pg: bool = False` (line 126):
```python
    scuffedos_managed_pg: bool = False           # env SCUFFEDOS_MANAGED_PG
    # Loopback port the backend listens on. Dev = uvicorn's 8000; packaged = the
    # random port the Tauri shell picks and exports as SCUFFEDOS_PORT (lib.rs).
    # GoogleProvider embeds this in the computed redirect URI when
    # google_redirect_uri is empty (M9 s2). No env_prefix/alias -> binds SCUFFEDOS_PORT.
    scuffedos_port: int = 8000                   # env SCUFFEDOS_PORT
```
- [ ] Run tests, confirm PASS. `cd backend && ../.venv/bin/python -m pytest tests/test_ship_config.py -q` → expected: the two new tests pass. Then full suite `cd backend && ../.venv/bin/python -m pytest -q` → expected **+2 new → `689 passed, 1 skipped`**.
- [ ] Commit. `git commit -am "feat(config): add scuffedos_port (binds SCUFFEDOS_PORT) for packaged loopback redirect (M9 s2)"`

---

### Task 2: redirect URI — empty default computes runtime loopback; non-empty wins verbatim (BOTH legs lock-step)

Files:
- Modify: `backend/app/config.py:88` (`google_redirect_uri` default `"http://localhost:8000/auth/google/callback"` → `""`)
- Modify: `backend/app/providers/google.py` — add a `_redirect_uri()` helper; use it in `authorize_url` (line 203) and `exchange_code` (line 235)
- Modify: `backend/tests/test_email_config.py:12` (update the default assertion)
- Test: `backend/tests/test_google_oauth.py` (add three tests after `test_authorize_url_has_all_oauth_params_and_offline_consent`, ~line 72)

Interfaces:
- Consumes: `settings.google_redirect_uri: str`, `settings.scuffedos_port: int` (Task 1).
- Produces: `GoogleProvider._redirect_uri() -> str` returning `settings.google_redirect_uri or f"http://127.0.0.1:{settings.scuffedos_port}/auth/google/callback"`; both OAuth legs stay in lock-step (same value in authorize + exchange). The exchange-leg test below is the guard that proves the exchange leg was actually switched to `_redirect_uri()` (§9 both-legs-match requirement).

Steps:

- [ ] Write the failing tests. Add to `backend/tests/test_google_oauth.py` (`FakeHttp`, `FakeResp`, `GOOGLE_TOKEN_URL` already imported/defined in this file):
```python
def test_authorize_url_computes_loopback_when_redirect_empty(monkeypatch):
    monkeypatch.setattr(settings, "google_redirect_uri", "")
    monkeypatch.setattr(settings, "scuffedos_port", 4300)
    settings.google_client_id = "gid"
    url = GoogleProvider().authorize_url("st8")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["http://127.0.0.1:4300/auth/google/callback"]


def test_authorize_url_uses_env_redirect_verbatim_when_set(monkeypatch):
    monkeypatch.setattr(settings, "google_redirect_uri", "https://tunnel.example/auth/google/callback")
    monkeypatch.setattr(settings, "scuffedos_port", 4300)
    url = GoogleProvider().authorize_url("st8")
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["https://tunnel.example/auth/google/callback"]


def test_exchange_code_uses_computed_loopback_when_redirect_empty(monkeypatch):
    # §9 lock-step: the EXCHANGE leg must embed the SAME computed loopback the
    # authorize leg does. Guards against exchange_code being left on the raw
    # settings.google_redirect_uri (which is "" now) instead of _redirect_uri().
    monkeypatch.setattr(settings, "google_redirect_uri", "")
    monkeypatch.setattr(settings, "scuffedos_port", 4300)
    settings.google_client_id = "gid"
    settings.google_client_secret = "gsecret"
    p = GoogleProvider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {"access_token": "AT", "expires_in": 3600}),
    }))
    p.exchange_code("thecode")
    _, data = p._http.posts[0]
    assert data["redirect_uri"] == "http://127.0.0.1:4300/auth/google/callback"
```
- [ ] Run them, confirm the two loopback tests FAIL. `cd backend && ../.venv/bin/python -m pytest tests/test_google_oauth.py -k loopback -q` → expected FAIL on BOTH `..._authorize_url_computes_loopback...` and `..._exchange_code_uses_computed_loopback...`: current code returns `settings.google_redirect_uri` (now `""`) on both legs, so `redirect_uri` is empty, not the computed loopback. NOTE: `test_authorize_url_uses_env_redirect_verbatim_when_set` is deliberately NOT in this `-k loopback` selection — it already passes pre-impl (current `authorize_url` emits `settings.google_redirect_uri` verbatim) and is a locked-in guard that the override-wins semantics survive the refactor, not a TDD-red.
- [ ] Minimal implementation — config default. In `backend/app/config.py`, change line 88:
```python
    google_redirect_uri: str = ""   # empty -> GoogleProvider computes http://127.0.0.1:{scuffedos_port}/auth/google/callback at request time (M9 s2); a non-empty env value wins verbatim
```
- [ ] Minimal implementation — provider helper. In `backend/app/providers/google.py`, add a helper just above `authorize_url` (line 198) and use it in both legs:
```python
    def _redirect_uri(self) -> str:
        # Empty -> compute the loopback callback from the live port (dev 8000 /
        # packaged random). A non-empty env value wins verbatim (registered
        # tunnel etc.). Both OAuth legs MUST use this so redirect_uri matches.
        return (settings.google_redirect_uri
                or f"http://127.0.0.1:{settings.scuffedos_port}/auth/google/callback")
```
Then in `authorize_url` change line 203 `"redirect_uri": settings.google_redirect_uri,` → `"redirect_uri": self._redirect_uri(),`, and in `exchange_code` change line 235 `"redirect_uri": settings.google_redirect_uri,` → `"redirect_uri": self._redirect_uri(),`.
- [ ] Update the default assertion. In `backend/tests/test_email_config.py:12`:
```python
    assert d["google_redirect_uri"].default == ""
```
- [ ] Run tests, confirm PASS. `cd backend && ../.venv/bin/python -m pytest tests/test_google_oauth.py tests/test_email_config.py -q` → expected all pass (note: existing `test_exchange_code_returns_tokens` at test_google_oauth.py:87 asserts `data["redirect_uri"] == settings.google_redirect_uri`, still true because `_provider()` sets a non-empty value → verbatim path). Then full suite `cd backend && ../.venv/bin/python -m pytest -q` → expected **+3 new → `692 passed, 1 skipped`**.
- [ ] Commit. `git commit -am "feat(oauth): compute loopback google_redirect_uri at request time when empty; both OAuth legs lock-step (M9 s2)"`

---

### Task 3: widen `authorize_url`/`exchange_code` signatures across every impl + fake (no behavior change)

This is the coordinated protocol-signature change. It lands in ONE commit — every implementer and every fake accepts the two new optional params (default `None`), unused. The suite stays green because all existing callers still pass old positional args.

Files (all **14** census sites — 13 from the providers verifier report PLUS the in-test override `ExchangeBoom` at `tests/test_oauth.py:139`, confirmed by `grep -rn "def authorize_url\|def exchange_code" app/ tests/`):
- Modify: `backend/app/providers/base.py:174-175` (protocol)
- Modify: `backend/app/providers/google.py:198, 231` (real impl — signatures only in this task; consumption lands in Task 4)
- Modify: `backend/app/providers/whoop.py:89, 116` (accept + ignore)
- Modify: `backend/app/providers/moodle.py:394, 402` (accept + ignore)
- Modify: `backend/tests/fakes.py:123, 129` (`FakeProvider`), `:365, 371` (`FakeEmailProvider`), `:467, 473` (`FakeMoodleProvider`)
- Modify: `backend/tests/test_provider_registry.py:12-13` (`FakePull`), `:25-26` (`FakePush`)
- Modify: `backend/tests/test_providers_base.py:68-69` (`_MinimalProvider`; do NOT touch `Broken` at :85-89)
- Modify: `backend/tests/test_moodle_provider.py:87-88` (`_Impl`)
- Modify: `backend/tests/test_fitness_sync.py:30-34` (`FakeProvider`; covers `_AuthFailProvider`/`_BoomProvider` via inheritance)
- Modify: `backend/tests/test_oauth.py:139` (`ExchangeBoom.exchange_code` — a NARROW override of the widened base; if left at `def exchange_code(self, code: str):` it shadows the widened `FakeProvider.exchange_code` and, once Task 4 makes the router call `impl.exchange_code(code, verifier=verifier)`, raises `TypeError: exchange_code() got an unexpected keyword argument 'verifier'` BEFORE its intended `RuntimeError` — the broad `except Exception` masks it green, so the regression test would pass for the WRONG reason. Widen it here.)
- Test: `backend/tests/test_providers_base.py` (add one signature-acceptance test)

Interfaces:
- Produces (target signature for all sites):
```python
def authorize_url(self, state: str, code_challenge: str | None = None) -> str: ...
def exchange_code(self, code: str, verifier: str | None = None) -> Tokens: ...
```
- Consumes: nothing new; params are accepted and ignored everywhere except Google (Task 4).

Steps:

- [ ] Write the failing test. Add to `backend/tests/test_providers_base.py` (uses the existing `_MinimalProvider` fake in that file):
```python
def test_oauth_methods_accept_optional_pkce_params():
    p = _MinimalProvider()
    # New optional PKCE params must be accepted by every OAuthProvider signature.
    assert p.authorize_url("st8", code_challenge="chal") == ""
    p.exchange_code("code", verifier="vrf")  # must not raise TypeError
```
- [ ] Run it, confirm FAIL. `cd backend && ../.venv/bin/python -m pytest tests/test_providers_base.py::test_oauth_methods_accept_optional_pkce_params -q` → expected FAIL: `TypeError: authorize_url() got an unexpected keyword argument 'code_challenge'`.
- [ ] Re-run the census grep to confirm no in-test override was missed. `cd backend && grep -rn "def authorize_url\|def exchange_code" app/ tests/` → expect exactly the 14 sites above (`test_providers_base.py:88` `Broken.authorize_url` is the only one intentionally left alone; it has NO `exchange_code`). Widen every match except `Broken`.
- [ ] Minimal implementation — protocol. In `backend/app/providers/base.py`, lines 174–175:
```python
    def authorize_url(self, state: str, code_challenge: str | None = None) -> str: ...
    def exchange_code(self, code: str, verifier: str | None = None) -> Tokens: ...
```
- [ ] Minimal implementation — real impls (signature only; Google body change is Task 4):
  - `app/providers/google.py:198` → `def authorize_url(self, state: str, code_challenge: str | None = None) -> str:`
  - `app/providers/google.py:231` → `def exchange_code(self, code: str, verifier: str | None = None) -> Tokens:`
  - `app/providers/whoop.py:89` → `def authorize_url(self, state: str, code_challenge: str | None = None) -> str:`
  - `app/providers/whoop.py:116` → `def exchange_code(self, code: str, verifier: str | None = None) -> Tokens:`
  - `app/providers/moodle.py:394` → `def authorize_url(self, state: str, code_challenge: str | None = None) -> str:`
  - `app/providers/moodle.py:402` → `def exchange_code(self, code: str, verifier: str | None = None) -> Tokens:`
- [ ] Minimal implementation — `tests/fakes.py` (all three): widen each pair, body unchanged:
  - `:123` → `def authorize_url(self, state: str, code_challenge: str | None = None) -> str:` ; `:129` → `def exchange_code(self, code: str, verifier: str | None = None) -> Tokens:`
  - `:365` → same authorize widen ; `:371` → same exchange widen
  - `:467` → same authorize widen ; `:473` → same exchange widen
- [ ] Minimal implementation — inline test fakes:
  - `test_provider_registry.py:12` → `def authorize_url(self, state, code_challenge=None): return f"https://fake/auth?state={state}"` ; `:13` → `def exchange_code(self, code, verifier=None): return Tokens("a", "r", None)`
  - `test_provider_registry.py:25` → `def authorize_url(self, state, code_challenge=None): return ""` ; `:26` → `def exchange_code(self, code, verifier=None): return Tokens("a", None, None)`
  - `test_providers_base.py:68` → `def authorize_url(self, state, code_challenge=None): return ""` ; `:69` → `def exchange_code(self, code, verifier=None): return Tokens("a", None, None)`
  - `test_moodle_provider.py:87` → `def authorize_url(self, state, code_challenge=None): return ""` ; `:88` → `def exchange_code(self, code, verifier=None): ...`
  - `test_oauth.py:139` (`ExchangeBoom`) → `def exchange_code(self, code, verifier=None):` (body unchanged — still `raise RuntimeError("token endpoint 500")`). This keeps the exchange-failure regression test exercising a REAL exchange exception, not a kwarg-mismatch TypeError, once Task 4 passes `verifier=`.
  - `test_fitness_sync.py:30-31` → `def authorize_url(self, state, code_challenge=None):` / `return f"https://example.test/auth?state={state}"` ; `:33-34` → `def exchange_code(self, code, verifier=None):` / `return Tokens(access_token="a", refresh_token="r", expires_at=None)`
  - Do NOT touch `test_providers_base.py:85-89` `Broken` (it intentionally omits `exchange_code` to fail an isinstance check).
- [ ] Run tests, confirm PASS. `cd backend && ../.venv/bin/python -m pytest -q` → expected **+1 new → `693 passed, 1 skipped`** (new acceptance test passes; nothing regresses).
- [ ] Commit. `git commit -am "refactor(providers): widen authorize_url/exchange_code with optional PKCE params across all impls+fakes (M9 s2)"`

---

### Task 4: PKCE (S256) flow — router mints verifier, stores tuple, Google consumes challenge+verifier

Files:
- Modify: `backend/app/routers/oauth.py` — imports (add `base64`, `hashlib`), `_STATES` type (line 31), `_issue_state` (36–39), `_consume_state` (42–44), `connect` (61–62), `oauth_callback` CSRF unpack (117–119) + exchange call (127)
- Modify: `backend/app/providers/google.py` — `authorize_url` body (append `code_challenge` + `code_challenge_method=S256` when passed), `exchange_code` body (add `code_verifier` to the POST when passed)
- Modify: `backend/tests/test_oauth.py:41` (`_STATES.get(state)` tuple assertion inside `test_connect_stores_a_one_time_state_server_side`)
- Test: `backend/tests/test_oauth.py` (add the verifier round-trip test AND the connect-side challenge-derivation test); `backend/tests/test_google_oauth.py` (add challenge/verifier tests)

Interfaces:
- Consumes: widened signatures from Task 3.
- Produces: `_STATES: dict[str, tuple[str, str]]` mapping `state -> (provider, verifier)`; `connect` calls `impl.authorize_url(state, code_challenge=<S256(verifier)>)`; `oauth_callback` calls `impl.exchange_code(code, verifier=<stored verifier>)`. Google's `authorize_url` emits `code_challenge` + `code_challenge_method=S256`; Google's `exchange_code` adds `code_verifier` to the token POST (`[confirm-against-live]` exact field name — RFC 7636 §4.5 says `code_verifier`). Other providers ignore both.

Steps:

- [ ] Write the failing tests. Update `backend/tests/test_oauth.py:41` and add PKCE tests. Replace line 41's assertion body inside `test_connect_stores_a_one_time_state_server_side`:
```python
def test_connect_stores_a_one_time_state_server_side(client):
    providers.configure([FakeProvider()])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    stored = oauth._STATES.get(state)
    assert isinstance(stored, tuple) and stored[0] == "whoop" and isinstance(stored[1], str) and stored[1]
    state2 = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    assert state2 != state
```
Add a connect-side test that proves `connect` passes `authorize_url` a challenge DERIVED (S256) from the STORED verifier — this covers the §13 requirement end-to-end (both the connect→authorize wiring AND the S256 base64url-no-pad correctness). A challenge-recording spy fake is needed because `FakeProvider.authorize_url` ignores `code_challenge`. Add near the other connect tests:
```python
def test_connect_derives_s256_challenge_from_the_stored_verifier(client):
    import base64
    import hashlib

    class ChallengeSpy(FakeProvider):
        def __init__(self):
            super().__init__()
            self.seen_challenge = "MISSING"
        def authorize_url(self, state, code_challenge=None):
            self.seen_challenge = code_challenge
            return super().authorize_url(state)

    spy = ChallengeSpy()
    providers.configure([spy])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    verifier = oauth._STATES[state][1]
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert spy.seen_challenge == expected
```
Add a callback round-trip test that proves the STORED verifier reaches `exchange_code` (uses a fake that records the verifier). Add near the other callback tests:
```python
def test_callback_passes_stored_verifier_into_exchange(client):
    class VerifierSpy(FakeProvider):
        def __init__(self):
            super().__init__()
            self.seen_verifier = "MISSING"
        def exchange_code(self, code, verifier=None):
            self.seen_verifier = verifier
            return super().exchange_code(code)
    spy = VerifierSpy()
    providers.configure([spy])
    state = _state_of(client.get("/api/oauth/connect/whoop").json()["authorize_url"])
    stored_verifier = oauth._STATES[state][1]
    res = client.get(f"/auth/whoop/callback?code=the-code&state={state}", follow_redirects=False)
    assert res.status_code == 200
    assert spy.seen_verifier == stored_verifier
```
- [ ] Run them, confirm FAIL. `cd backend && ../.venv/bin/python -m pytest tests/test_oauth.py -k "one_time_state or derives_s256 or stored_verifier" -q` → expected FAIL: `_STATES.get(state)` is currently the bare string `"whoop"` (not a tuple); `connect` calls `impl.authorize_url(state)` with no `code_challenge` (spy stays `"MISSING"`); and `exchange_code` is called without a verifier (`seen_verifier` stays `None`/`MISSING`, not the stored value).
- [ ] Minimal implementation — router. In `backend/app/routers/oauth.py`:
  - Add imports near the top (after `import secrets`, line 16):
```python
import base64
import hashlib
```
  - Change `_STATES` (line 31):
```python
# state token -> (provider name, PKCE verifier). One-time; in-process is fine
# for a single-user desktop app. Slice 2 added the verifier for Google PKCE.
_STATES: dict[str, tuple[str, str]] = {}
```
  - Replace `_issue_state` (36–39) and `_consume_state` (42–44):
```python
def _issue_state(provider: str) -> tuple[str, str]:
    """Return (state, code_challenge). Stores (provider, verifier) one-time."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)                      # RFC 7636 high-entropy verifier
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()                                   # S256 challenge, base64url no pad
    _STATES[state] = (provider, verifier)
    return state, challenge


def _consume_state(state: str) -> tuple[str, str] | None:
    """Pop (provider, verifier) for a state (one-time use)."""
    return _STATES.pop(state, None)
```
  - Update `connect` (61–62):
```python
    state, challenge = _issue_state(provider)
    return {"authorize_url": impl.authorize_url(state, code_challenge=challenge)}
```
  - Update `oauth_callback` CSRF + exchange. The consume now returns a tuple; unpack it (lines 117–119 and 127):
```python
    issued = _consume_state(state)
    if issued is None or issued[0] != provider:
        return _callback_error("This sign-in link has expired or is invalid.")
    verifier = issued[1]
```
    and the exchange call at line 127:
```python
        tokens = impl.exchange_code(code, verifier=verifier)
```
- [ ] Minimal implementation — Google consumes the params. In `backend/app/providers/google.py` `authorize_url`, build the dict conditionally (lines 201–209):
```python
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": self._redirect_uri(),
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        q = urlencode(params)
        return f"{GOOGLE_AUTH_URL}?{q}"
```
  and in `exchange_code` (lines 232–238):
```python
    def exchange_code(self, code: str, verifier: str | None = None) -> Tokens:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri(),
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        }
        if verifier is not None:
            data["code_verifier"] = verifier   # [confirm-against-live] RFC 7636 field name
        return self._token_request(data)
```
- [ ] Write/confirm the Google-side unit tests. Add to `backend/tests/test_google_oauth.py`:
```python
def test_authorize_url_adds_s256_challenge_when_passed():
    p = _provider()
    url = p.authorize_url("st8", code_challenge="CHALLENGE")
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge"] == ["CHALLENGE"]
    assert q["code_challenge_method"] == ["S256"]


def test_authorize_url_omits_challenge_when_none():
    p = _provider()
    q = parse_qs(urlparse(p.authorize_url("st8")).query)
    assert "code_challenge" not in q


def test_exchange_code_includes_code_verifier_when_passed():
    p = _provider()
    p.configure(fake_http=FakeHttp({
        GOOGLE_TOKEN_URL: FakeResp(200, {"access_token": "AT", "expires_in": 3600}),
    }))
    p.exchange_code("thecode", verifier="VRF")
    _, data = p._http.posts[0]
    assert data["code_verifier"] == "VRF"
```
- [ ] Run tests, confirm PASS. `cd backend && ../.venv/bin/python -m pytest tests/test_oauth.py tests/test_google_oauth.py -q` → expected all pass. Then full suite `cd backend && ../.venv/bin/python -m pytest -q` → expected **+5 new → `698 passed, 1 skipped`** (the five new tests: `test_connect_derives_s256_challenge_from_the_stored_verifier`, `test_callback_passes_stored_verifier_into_exchange`, `test_authorize_url_adds_s256_challenge_when_passed`, `test_authorize_url_omits_challenge_when_none`, `test_exchange_code_includes_code_verifier_when_passed`; the `test_connect_stores_...` rewrite is net-0).
- [ ] Commit. `git commit -am "feat(oauth): PKCE S256 flow — mint verifier, store (provider,verifier), Google consumes challenge+verifier (M9 s2)"`

---

### Task 5: Tauri — export `SCUFFEDOS_PORT` into the sidecar env

Files:
- Modify: `src-tauri/src/lib.rs:204-210` (the sidecar spawn builder chain; add one `.env(...)` alongside the existing two at lines 207–208)

Interfaces:
- Consumes: `port: u16` (already bound at `lib.rs:198` via `let port = free_port();`).
- Produces: sidecar env var `SCUFFEDOS_PORT={port}`, which `config.py`'s `scuffedos_port` (Task 1) binds and `GoogleProvider._redirect_uri()` (Task 2) embeds.

Steps:

- [ ] Add the env export. In `src-tauri/src/lib.rs`, insert one line inside the builder chain (after line 208, before `.args(...)` at line 209):
```rust
                .env("SCUFFEDOS_MANAGED_PG", "1")
                .env("RESOURCES_PGSQL_DIR", pgsql_res.to_string_lossy().to_string())
                .env("SCUFFEDOS_PORT", port.to_string())
                .args(["--port", &port.to_string()])
```
- [ ] Verify the Rust compiles. `cd src-tauri && cargo check --offline` → expected: `Finished ... target(s)` with zero errors (no new dependency, offline cache is sufficient — confirmed feasible by the tauri verifier report).
- [ ] Commit. `git commit -am "feat(ship): export SCUFFEDOS_PORT to the sidecar so the loopback redirect matches the live port (M9 s2)"`

---

### Task 6: Tauri — add the opener plugin (dependency + capability + registration)

Files:
- Modify: `src-tauri/Cargo.toml:14-20` (add `tauri-plugin-opener = "2"` under `[dependencies]`)
- Modify: `src-tauri/src/lib.rs:195` (add `.plugin(tauri_plugin_opener::init())`)
- Modify: `src-tauri/capabilities/default.json` (add the opener permission to the `permissions` array)

Interfaces:
- Produces: the Rust-side opener plugin the frontend `openUrl` call (Task 7) invokes to open the system browser. NO deep-link/scheme (slice 3).

> EXECUTION RISK — network/registry required, no offline path. This task's `cargo check` drops `--offline` to download `tauri-plugin-opener`, and the tauri verifier confirmed ONLY that the toolchain is present and `cargo check --offline` works — it did NOT confirm outbound network. The build step below is therefore a SOFT gate: if the crate cannot be fetched, do NOT treat it as a plan failure — record the blocker and hand the packaged build off to the user (see Manual verification / live gate). The `[confirm-against-live]` opener permission identifier can only be resolved AFTER the crate is fetched (the ACL regenerates under `gen/schemas/` on that first non-offline build), so it too is deferred to this build and is a live execution risk.

Steps:

- [ ] Add the dependency. In `src-tauri/Cargo.toml`, under `[dependencies]` (next to `tauri-plugin-shell = "2"` at line 16):
```toml
tauri-plugin-opener = "2"
```
- [ ] Register the plugin. In `src-tauri/src/lib.rs`, add a second chained `.plugin(...)` right after line 195:
```rust
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
```
- [ ] Grant the capability. In `src-tauri/capabilities/default.json`, add the opener permission to the `"permissions"` array (after `"core:default"`):
```json
  "permissions": [
    "core:default",
    "opener:default",
    {
      "identifier": "shell:allow-spawn",
```
  `[confirm-against-live]` the exact opener v2 permission identifier (`"opener:default"` vs a scoped `"opener:allow-open-url"`). After the dependency is fetched, confirm against the plugin's generated ACL under `src-tauri/gen/schemas/` and adjust if `opener:default` is rejected. Do NOT hand-edit `gen/schemas/*` — they regenerate on build.
- [ ] Fetch + compile (SOFT gate — needs network to download the new crate; drop `--offline`). `cd src-tauri && cargo check` → expected: downloads `tauri-plugin-opener`, then `Finished ... target(s)` with zero errors. If `opener:default` is not a valid identifier, the ACL codegen fails with a clear message naming the valid identifiers — switch to the scoped one it lists and re-run. If the crate cannot be fetched at all (no network/registry), STOP and hand the packaged build to the user rather than reporting task failure — this is a known execution risk, not a plan defect.
- [ ] Commit. `git commit -am "feat(ship): add tauri-plugin-opener (dep + capability + registration) for system-browser OAuth/Plaid open (M9 s2)"`

---

### Task 7: frontend — route Connect/Plaid-link through the opener under `isTauri()`

Files:
- Modify: `frontend/package.json` (add `@tauri-apps/plugin-opener` to `dependencies`)
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (import `isTauri`, make `openExternal` branch on packaged mode; lines 6–9 imports and 28–33 helper)

Interfaces:
- Consumes: `isTauri()` from `@tauri-apps/api/core` (already a dependency, used in `main.jsx`); `openUrl` from `@tauri-apps/plugin-opener` (Task 6's Rust side backs it).
- Produces: an `async openExternal(url)` that opens the system browser in packaged mode and keeps `window.open` in dev. Built on Slice-1's existing `openExternal`; every existing call site (`connectOAuth`, `startLink`, `reauthItem`) passes just `openExternal(url)` and is unchanged.

> EXECUTION RISK — npm registry required, no offline path. The install step needs registry access, and `npm run build` then hard-fails to resolve the dynamic `import('@tauri-apps/plugin-opener')` if the install did not land. The frontend verifier did NOT confirm registry access. Treat the build as a SOFT gate: if the package cannot be installed, record the blocker and defer the packaged build to the user. The `[confirm-against-live]` `openUrl` export name is likewise resolved only against the installed package's `dist` types — deferred to this install and a live execution risk.

Steps:

- [ ] Install the JS package (SOFT gate — needs npm registry access). `cd frontend && npm install @tauri-apps/plugin-opener@^2` → expected: adds `"@tauri-apps/plugin-opener": "^2..."` to `frontend/package.json` dependencies and updates the lockfile. `[confirm-against-live]` the exported JS function name — this plan assumes `openUrl(url)`; confirm against the installed package's `dist` types (v2 exports `openUrl`/`openPath`). If the registry is unreachable, STOP and hand the packaged build to the user rather than reporting task failure.
- [ ] Add the import. In `frontend/src/screens/ConnectorsPanel.jsx`, after line 9 (`import { api } ...`):
```js
import { isTauri } from '@tauri-apps/api/core'
```
- [ ] Rewrite `openExternal` (lines 28–33) to branch on packaged mode (drop the unused `sameWindow` option — no call site passes it, per the frontend verifier):
```js
// Open an OAuth/hosted-link URL. In the packaged app (isTauri) route through the
// Tauri opener plugin so consent happens in the user's real system browser with
// their live session; in dev keep the webview new-tab behavior.
async function openExternal(url) {
  if (isTauri()) {
    const { openUrl } = await import('@tauri-apps/plugin-opener')
    await openUrl(url)
    return
  }
  window.open(url, '_blank', 'noopener')
}
```
  (Callers already `openExternal(...)` fire-and-forget; the added `async`/Promise is harmless. The dynamic `import()` keeps the opener chunk out of the dev bundle path but Vite still resolves it — hence the install step above.)
- [ ] Verify the build (SOFT gate). `cd frontend && npm run build` → expected: `vite build` completes with `✓ built in ...` and exit code 0 (no unresolved `@tauri-apps/plugin-opener`). If the install did not land, this fails to resolve the dynamic import — defer to the user build rather than reporting task failure.
- [ ] Manual checklist note (no harness): in dev (`npm run dev`, browser) `isTauri()` is false → Connect still opens a new tab (same open behavior as Slice 1). The post-connect auto-poll added in Task 8 also runs in dev — a harmless auto-refresh, not a regression. Packaged verification is the live gate below.
- [ ] Commit. `git commit -am "feat(connectors): route Connect + Plaid link through Tauri opener under isTauri() (M9 s2)"`

---

### Task 8: frontend — poll `GET /api/connectors` after Connect until the connector's snapshot tuple changes

Files:
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (add a poll ref + effect cleanup; add `startConnectPoll`; call it from `connectOAuth`)

Interfaces:
- Consumes: `api.getConnectors()` (returns the connector array), the current `connectors` state (for the pre-click snapshot).
- Produces: a bounded poll that stops when the target connector's `(status, can_write_email, connected_at)` tuple changes from its pre-click snapshot, on ~2min timeout, or on unmount. Explicitly NOT "until status flips" — the scope-upgrade reconnect keeps `status='connected'` and only moves `can_write_email`. The poll runs in BOTH dev and packaged mode (no `isTauri()` guard); in dev it is a harmless auto-refresh that self-stops. This is the one intentional dev-behavior change in Slice 2 (see Goal).

Steps:

- [ ] Add the poll machinery. In `frontend/src/screens/ConnectorsPanel.jsx`, after the `refresh` effect (line 54) add:
```js
  const pollRef = React.useRef(null)
  React.useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const snapshotOf = (c) => `${c?.status}|${c?.can_write_email}|${c?.connected_at}`

  // From a Connect click, poll the connectors read model (~2s, bounded ~2min) and
  // stop as soon as THIS connector's (status, can_write_email, connected_at) tuple
  // changes from its pre-click snapshot — covers both first-connect AND the
  // scope-upgrade reconnect (status stays 'connected', only can_write_email moves).
  const startConnectPoll = (name) => {
    const before = snapshotOf((connectors || []).find((c) => c.name === name))
    if (pollRef.current) clearInterval(pollRef.current)
    let ticks = 0
    pollRef.current = setInterval(() => {
      ticks += 1
      api.getConnectors().then((list) => {
        const now = snapshotOf(list.find((c) => c.name === name))
        if (now !== before) {
          clearInterval(pollRef.current); pollRef.current = null
          setConnectors(list); setError('')
        } else if (ticks >= 60) {          // ~2 min at 2s
          clearInterval(pollRef.current); pollRef.current = null
        }
      }).catch(() => {})
    }, 2000)
  }
```
- [ ] Wire it into `connectOAuth` (lines 56–61):
```js
  const connectOAuth = (name) => {
    setBusy(name)
    api.oauthConnect(name)
      .then((r) => { openExternal(r.authorize_url); setBusy(''); startConnectPoll(name) })
      .catch((e) => { setError(e?.message || 'Connect failed'); setBusy('') })
  }
```
- [ ] Verify the build. `cd frontend && npm run build` → expected: `✓ built in ...`, exit 0.
- [ ] Manual checklist note: after clicking Connect and completing consent in the system browser, the card flips to Connected within ~2s without any user tab-switch; the poll self-stops on flip, on ~2min timeout, or when the Connectors tab/screen unmounts. In dev the same poll runs and self-stops harmlessly.
- [ ] Commit. `git commit -am "feat(connectors): poll /api/connectors after Connect until the connector snapshot tuple changes (M9 s2)"`

---

### Task 9: frontend — WHOOP shows "requires the signed build (slice 3)" in packaged mode

Files:
- Modify: `frontend/src/screens/ConnectorsPanel.jsx` (compute a packaged flag; gate the WHOOP Connect/Reconnect buttons in the `auth_kind === 'oauth'` block, lines 162–181)

Interfaces:
- Consumes: `isTauri()` (Task 7 import).
- Produces: in packaged mode, WHOOP's Connect/Reconnect is replaced by a disabled control + "requires the signed build (slice 3)" note; dev (not packaged) WHOOP connect is unchanged; Google is unaffected in both modes.

Steps:

- [ ] Add a packaged flag near the other derived values (before `return`, e.g. after `connectDisabled`, line 122):
```js
  const packaged = isTauri()
```
- [ ] Gate WHOOP inside the OAuth block. In the `auth_kind === 'oauth'` div (lines 162–181), wrap the WHOOP connect/reconnect so packaged WHOOP shows the slice-3 note instead of a live button:
```jsx
            {c.auth_kind === 'oauth' && (
              <div className="kit-inline" style={{ gap: 8 }}>
                {packaged && c.name === 'whoop' && c.status !== 'connected' ? (
                  <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}>
                    WHOOP sign-in requires the signed build (slice 3).
                  </span>
                ) : (
                  <>
                    {c.status === 'not_connected' && (
                      <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                        onClick={() => connectOAuth(c.name)}>Connect</Button>
                    )}
                    {c.status === 'needs_reauth' && (
                      <Button variant="primary" size="sm" disabled={connectDisabled(c)}
                        onClick={() => connectOAuth(c.name)}>Reconnect</Button>
                    )}
                    {c.status === 'connected' && c.name === 'google' && c.can_write_email === false && (
                      <Button variant="secondary" size="sm" disabled={connectDisabled(c)}
                        onClick={() => connectOAuth(c.name)}>Enable email actions</Button>
                    )}
                  </>
                )}
                {c.status !== 'not_connected' && confirming !== c.name && (
                  <Button variant="secondary" size="sm" disabled={busy === c.name}
                    onClick={() => setConfirming(c.name)}>Disconnect</Button>
                )}
              </div>
            )}
```
  (Disconnect stays available so an already-connected WHOOP account can still be removed in packaged mode.)
- [ ] Verify the build. `cd frontend && npm run build` → expected: `✓ built in ...`, exit 0.
- [ ] Manual checklist note: in dev, WHOOP Connect still opens the tunnel-redirect flow as today; only packaged mode shows the slice-3 note.
- [ ] Commit. `git commit -am "feat(connectors): gate WHOOP connect behind the signed build (slice 3) in packaged mode (M9 s2)"`

---

## Manual verification / live gate (user) [confirm-against-live]

The packaged-.app end-to-end is NOT an SDD task (no automated harness can drive a real system browser + Google/Plaid consent + the loopback callback). Two build gates (Task 6 `cargo check` non-offline, Task 7 `npm install` + `npm run build`) require network/registry access the verifiers did NOT confirm; if the implementer cannot fetch, those tasks and the packaged build hand off here. **Dev-side change to disclose (final-review finding M2, by-design):** making `google_redirect_uri` default `""` means dev now computes `http://127.0.0.1:{scuffedos_port}/auth/google/callback` — i.e. the dev default flips from `localhost:8000` to **`127.0.0.1:8000`**. Google treats those as *distinct* redirect URIs. This is correct and required for the packaged Desktop-client loopback (where `127.0.0.1:<any-port>` is auto-allowed), but it means **dev Google OAuth will fail with `redirect_uri_mismatch` if the dev is still on the old M5/M6 "Web application" client registered to `localhost:8000`** — until the dev either (a) migrates to a **Desktop** OAuth client (recommended; the same switch the live gate below requires), or (b) sets `google_redirect_uri=http://localhost:8000/auth/google/callback` (or the `127.0.0.1` form registered on the Web client) explicitly in the dev `.env` (a non-empty value wins verbatim). The plan's Goal note ("only intentional dev-side change is the poll") understates this; this bullet is the correction. WHOOP/Moodle/Plaid dev flows are unaffected.

After all nine tasks are merged and a fresh `.app` is built, the USER performs the §16 Slice-2 acceptance:

- [ ] [confirm-against-live] (Only if the implementer hit a network/registry block on Task 6/7) Run the deferred builds locally: `cd src-tauri && cargo check` (fetches `tauri-plugin-opener`; then resolve the opener permission identifier from `gen/schemas/` — `opener:default` vs scoped) and `cd frontend && npm install @tauri-apps/plugin-opener@^2 && npm run build` (confirm the `openUrl` export name against `dist` types).
- [ ] [confirm-against-live] In Google Cloud Console, switch the OAuth client type to **"Desktop app"** (or create a new Desktop client), then paste the new client id/secret into Settings › API keys (reuses `google_client_id`/`google_client_secret` — no code change).
- [ ] [confirm-against-live] Do the one-time Google **needs_reauth → Reconnect** in the Connectors tab (refresh tokens minted under the old Web client die with the client_id change — expected, and surfaced as an ordinary reconnect).
- [ ] [confirm-against-live] Build the packaged `.app` (build-app.sh) and launch it.
- [ ] [confirm-against-live] **Google:** click Connect → consent opens in the real **system browser** with the live Google session → the loopback `http://127.0.0.1:{scuffedos_port}/auth/google/callback` renders the §6a success page → the Connectors tab **poll** flips the card to Connected with no manual tab-switch.
- [ ] [confirm-against-live] **Plaid:** Link bank account → the hosted-link tab opens in the **system browser** → finish there → click **Finish linking** → the 409-poll completes and the item appears.
- [ ] [confirm-against-live] **Moodle:** paste the wstoken → connects with no redirect (already packaged-safe).
- [ ] [confirm-against-live] **Port proof:** confirm `scuffedos_port` provably reaches the redirect URI — the loopback callback the browser lands on carries the actual random sidecar port (e.g. inspect the callback URL / backend log), not `8000`. (The automated half of this proof is Task 2's `test_authorize_url_computes_loopback_when_redirect_empty` + `test_exchange_code_uses_computed_loopback_when_redirect_empty`.)
- [ ] WHOOP is expected to show "requires the signed build (slice 3)" in the packaged app — deferred to Slice 3.

## Open questions resolved / flagged

- **[config] Desktop-client fields:** RESOLVED — reuse existing `google_client_id`/`google_client_secret` and `SECRET_FIELD_MAP`; the GCP client-type swap is a paste, not a schema change. No new Settings fields.
- **[config] router reads `google_redirect_uri`?** RESOLVED — it does not; the two consumers are both in `GoogleProvider` (google.py authorize_url + exchange_code). Task 2 changes them via `_redirect_uri()`; the router is untouched for redirect construction.
- **[oauth] `_STATES` value type change:** CONFIRMED intended — Task 4 changes it to `tuple[str, str]` and updates test_oauth.py:41.
- **[providers] PKCE POST field name:** assumed `code_verifier` (RFC 7636 §4.5); flagged `[confirm-against-live]` in Task 4 and in the live gate.
- **[providers] census completeness:** the widen list is 14 sites (13 from the providers verifier + `ExchangeBoom` at test_oauth.py:139), re-confirmed by `grep -rn "def authorize_url\|def exchange_code" app/ tests/` inside Task 3. `test_providers_base.py:88` `Broken` is deliberately excluded.
- **[providers] fakes path / line drift:** the plan uses `backend/tests/fakes.py` (the real path; the spec's `backend/app/providers/fakes.py` is a typo) and the corrected lines `:371`/`:473` (not the spec's `:373`/`:462`).
- **[frontend] opener plugin choice + JS API:** chose `@tauri-apps/plugin-opener` with `openUrl`; flagged `[confirm-against-live]` on the exact export name (Task 7) and requires npm registry access to install (soft gate).
- **[frontend] auto-poll pattern:** none existed in-repo; Task 8 writes it from scratch against `api.getConnectors()` with the (status, can_write_email, connected_at) snapshot condition. The poll runs in both dev and packaged mode (intentional; noted in the Goal).
- **[tauri] opener permission identifier:** used `"opener:default"`; flagged `[confirm-against-live]` in Task 6 with a fallback to the scoped identifier the ACL codegen names, and noted the first opener build needs network (not `--offline`) — soft gate deferring to the user build if the crate cannot be fetched.

## Reviewer findings — adjudication

All 11 critique findings were verified against the live tree (`backend/tests/test_oauth.py`, `backend/tests/test_google_oauth.py`, `backend/app/routers/oauth.py`, and `grep -rn "def authorize_url\|def exchange_code" app/ tests/`). None was a false positive; every finding was APPLIED. Summary:

- **Findings 1 & 9 (ExchangeBoom census miss):** APPLIED. The grep confirms a 14th site, `tests/test_oauth.py:139` `class ExchangeBoom(FakeProvider): def exchange_code(self, code: str):`, absent from the draft's 13-site list. Left un-widened, Task 4's `impl.exchange_code(code, verifier=verifier)` would raise `TypeError` (masked green by the broad `except Exception`), so the exchange-failure regression test would pass for the wrong reason. Added to Task 3's widen list; census re-labelled 14 sites; added the in-task confirmation grep.
- **Finding 2 (S256 derivation + connect wiring untested):** APPLIED. Neither the FakeProvider router tests nor the literal-`code_challenge` Google test proves `connect` passes a challenge DERIVED from the stored verifier. Added `test_connect_derives_s256_challenge_from_the_stored_verifier` (ChallengeSpy) to Task 4, asserting `spy.seen_challenge == base64.urlsafe_b64encode(sha256(stored_verifier).digest()).rstrip(b"=").decode()`.
- **Finding 3 (exchange-leg loopback untested):** APPLIED. The pre-existing `test_exchange_code_returns_tokens` uses a non-empty redirect (verbatim path), so a regression leaving `exchange_code` on raw `settings.google_redirect_uri` would ship green. Added `test_exchange_code_uses_computed_loopback_when_redirect_empty` to Task 2.
- **Findings 4, 5, 7 (pass-count arithmetic):** APPLIED. Recomputed from the 687 baseline including the two coverage tests added by findings 2 & 3: Task 1 → 689 (+2), Task 2 → 692 (+3), Task 3 → 693 (+1), Task 4 → 698 (+5), all `1 skipped`. Each gate now states both the delta and the absolute.
- **Finding 6 (verbatim test is not RED):** APPLIED. Narrowed Task 2's confirm-FAIL command to `-k loopback` (matches both loopback tests) and documented that the verbatim test is a passing guard, not a TDD-red.
- **Finding 8 (network/registry build gates):** APPLIED. Marked Task 6 `cargo check` (non-offline) and Task 7 `npm install`/`npm run build` as SOFT gates with an explicit hand-off-to-user fallback, and noted both `[confirm-against-live]` resolutions (opener permission id, `openUrl` export name) are deferred to those live builds.
- **Finding 10 (dev auto-poll contradicts "dev unchanged"):** APPLIED (option a). Reworded the Goal and Task 7's checklist note to acknowledge Task 8's poll runs in both dev and packaged mode as a harmless auto-refresh; added an explicit note in Task 8.
- **Finding 11 (dead `sameWindow` param):** APPLIED. Simplified the Task 7 `openExternal` rewrite to `async function openExternal(url)` with just the `isTauri()`→`openUrl` branch and an `else window.open(url, '_blank', 'noopener')`; dropped the unused options object and `window.location` branch (no call site exercises it).
