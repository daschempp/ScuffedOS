"""Moodle browser sign-in: the passport-bound authorize URL and the launch
callback `POST /auth/moodle/launch` (outside /api).

NC State WolfWare is Shibboleth SSO, so there is no username/password token
endpoint. `GET /api/oauth/connect/moodle` issues a one-time state and returns
Moodle's mobile-app launch URL carrying it as the `passport`; the app opens
that in the system browser; Moodle redirects to `scuffedos://token=<blob>`
where `blob = base64(md5(wwwroot + passport) ':::' wstoken [':::' privatetoken])`;
the Tauri shell replays the blob to this endpoint in a JSON body. The md5 is
the ONLY thing tying a returning launch to a pending sign-in — there is no
`state` parameter to look up — so the endpoint searches the pending states for
the one whose signature matches, and burns it.

The blob travels in the BODY, never the URL: a query string would land in
uvicorn's access log (and from there the sidecar's stderr drain), and the blob
carries the wstoken.

Local fakes only (mirrors test_moodle_api.py) — no network.
"""
import base64
import hashlib
import logging
from urllib.parse import parse_qs, urlparse

import pytest

from app import moodle_sync, providers
from app.config import settings
from app.providers.moodle import MoodleAuthError, MoodleProvider
from app.routers import oauth
from app.store import store

from .fakes import FakeProvider

WSTOKEN = "a" * 32            # 32 lowercase hex, the live wstoken shape
PRIVATETOKEN = "p" * 32       # Moodle's optional third segment


class FakeMoodleProvider:
    """Slim MoodleProvider stand-in for the launch-callback tests (mirrors the
    one in test_moodle_api.py). Scripts get_site_info — the connect-time
    validation — and records the wstoken it was handed so a test can prove the
    blob was parsed, not the blob itself passed through. authorize_url
    delegates to the REAL provider so the passport under test is the real,
    state-bound one."""

    name = "moodle"

    def __init__(self, *, site_info=None, raise_auth=False):
        self._site_info = site_info or {
            "userid": 501, "sitename": "WolfWare", "release": "5.2",
            "functions": ["core_enrol_get_users_courses"],
        }
        self._raise_auth = raise_auth
        self.site_info_calls: list[str] = []

    def fetch_school_snapshot(self, since):  # marks this as a Moodle provider
        return None

    def authorize_url(self, state, code_challenge=None):
        return MoodleProvider().authorize_url(state, code_challenge)

    def get_site_info(self, token: str) -> dict:
        self.site_info_calls.append(token)
        if self._raise_auth:
            raise MoodleAuthError("invalidtoken")
        return dict(self._site_info)

    # ---- OAuth plumbing the shared oauth router calls on disconnect ----
    def set_tokens(self, tokens):
        pass

    def revoke(self, tokens) -> None:
        pass

    def on_disconnect(self) -> None:
        store.delete_moodle_data(self.name)


class FakeMoodleSync:
    """Stand-in installed via moodle_sync.configure(...). `boom` makes tick()
    raise, for the post-persist best-effort path."""

    def __init__(self, count=0, boom=False):
        self.count = count
        self.calls = 0
        self.boom = boom

    def tick(self, now=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("moodle sync exploded")
        return self.count


@pytest.fixture(autouse=True)
def clean_states():
    """oauth._STATES is module-level and survives tests; clear it so "the
    pending sign-in" in these assertions means exactly the one issued here."""
    oauth._STATES.clear()
    yield
    oauth._STATES.clear()


def _issue_passport(client) -> str:
    """Start a sign-in the way the frontend does, returning the passport."""
    res = client.get("/api/oauth/connect/moodle")
    assert res.status_code == 200
    return parse_qs(urlparse(res.json()["authorize_url"]).query)["passport"][0]


def _blob(passport, *, wstoken=WSTOKEN, privatetoken=PRIVATETOKEN) -> str:
    """The base64 payload Moodle hands back on the custom-scheme redirect."""
    signature = hashlib.md5((settings.moodle_base_url + passport).encode()).hexdigest()
    raw = f"{signature}:::{wstoken}"
    if privatetoken is not None:
        raw += f":::{privatetoken}"
    return base64.b64encode(raw.encode()).decode()


def _launch(client, blob: str):
    """What the Tauri shell fires: the raw blob in a JSON body."""
    return client.post("/auth/moodle/launch", json={"token": blob})


def _moodle_accounts() -> list[dict]:
    return [a for a in store.list_provider_accounts() if a["provider"] == "moodle"]


# ---- the authorize URL that starts the flow -------------------------------
def test_authorize_url_is_the_passport_bound_mobile_launch_url():
    url = MoodleProvider().authorize_url("abc")

    parsed = urlparse(url)
    assert url.startswith(settings.moodle_base_url)
    assert parsed.path == "/admin/tool/mobile/launch.php"
    assert parse_qs(parsed.query) == {
        "service": ["moodle_mobile_app"],
        "passport": ["abc"],
        "urlscheme": ["scuffedos"],
    }


def test_connect_moodle_binds_the_passport_to_the_issued_state(client):
    providers.configure([FakeMoodleProvider()])

    url = client.get("/api/oauth/connect/moodle").json()["authorize_url"]

    qs = parse_qs(urlparse(url).query)
    assert qs["service"] == ["moodle_mobile_app"]
    assert qs["urlscheme"] == ["scuffedos"]
    # The passport IS the one-time state: md5(wwwroot + passport) is what the
    # launch callback matches a returning blob against.
    assert list(oauth._STATES) == [qs["passport"][0]]
    assert oauth._STATES[qs["passport"][0]][0] == "moodle"


# ---- POST /auth/moodle/launch ---------------------------------------------
def test_launch_persists_the_account_kicks_sync_and_burns_the_state(client):
    fake_sync = FakeMoodleSync(count=3)
    moodle_sync.configure(fake_sync)
    fake = FakeMoodleProvider()
    providers.configure([fake])
    passport = _issue_passport(client)

    res = _launch(client, _blob(passport))

    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Connected" in res.text
    account = _moodle_accounts()[0]
    assert account["status"] == "connected"
    assert account["provider_user_id"] == "501"
    # The blob was parsed: the middle segment (not the blob) was validated.
    assert fake.site_info_calls == [WSTOKEN]
    assert fake_sync.calls == 1
    assert passport not in oauth._STATES


def test_launch_accepts_a_blob_containing_base64_plus_and_slash(client):
    """Standard base64 uses '+' and '/', which are exactly what a URL query
    would have mangled ('+' arrives as a space, and b64decode then silently
    DROPS it rather than restoring it, corrupting the decode). The JSON body
    carries them verbatim.

    Getting them into an ASCII payload takes a nudge: base64 only emits
    '+'/'/' where a byte at index 3k+2 has low six bits 111110/111111 — i.e.
    '>', '~' or '?'. Vary the padding of the (parser-ignored) private-token
    segment until both land on that boundary."""
    moodle_sync.configure(FakeMoodleSync())
    fake = FakeMoodleProvider()
    providers.configure([fake])
    passport = _issue_passport(client)
    for pad in range(3):
        blob = _blob(passport, privatetoken="x" * pad + "~xx?")
        if "+" in blob and "/" in blob:
            break
    else:  # pragma: no cover — one of the three alignments always matches
        raise AssertionError("no blob with '+' and '/' found")

    res = _launch(client, blob)

    assert res.status_code == 200
    assert fake.site_info_calls == [WSTOKEN]
    assert _moodle_accounts()[0]["status"] == "connected"


def test_launch_is_single_use_so_a_replay_is_rejected(client):
    moodle_sync.configure(FakeMoodleSync())
    providers.configure([FakeMoodleProvider()])
    blob = _blob(_issue_passport(client))

    assert _launch(client, blob).status_code == 200
    replay = _launch(client, blob)

    assert replay.status_code == 400
    assert len(_moodle_accounts()) == 1


def test_launch_with_an_unissued_passport_leaves_the_pending_sign_in_alone(client):
    # An intercepted/forged blob must not be able to burn a pending sign-in.
    fake_sync = FakeMoodleSync()
    moodle_sync.configure(fake_sync)
    providers.configure([FakeMoodleProvider()])
    passport = _issue_passport(client)

    res = _launch(client, _blob("never-issued"))

    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert _moodle_accounts() == []
    assert passport in oauth._STATES
    assert fake_sync.calls == 0


def test_launch_ignores_a_pending_state_issued_for_another_provider(client):
    # _STATES is shared across providers; a blob signed over a WHOOP/Google
    # state must neither connect Moodle nor burn that other sign-in.
    moodle_sync.configure(FakeMoodleSync())
    providers.configure([FakeMoodleProvider(), FakeProvider()])
    whoop_url = client.get("/api/oauth/connect/whoop").json()["authorize_url"]
    whoop_state = parse_qs(urlparse(whoop_url).query)["state"][0]

    res = _launch(client, _blob(whoop_state))

    assert res.status_code == 400
    assert _moodle_accounts() == []
    assert whoop_state in oauth._STATES


def test_launch_with_a_token_moodle_rejects_persists_nothing_but_burns_state(client):
    fake_sync = FakeMoodleSync()
    moodle_sync.configure(fake_sync)
    providers.configure([FakeMoodleProvider(raise_auth=True)])
    passport = _issue_passport(client)

    res = _launch(client, _blob(passport))

    assert res.status_code == 400
    assert _moodle_accounts() == []
    assert fake_sync.calls == 0
    # The signature DID match a pending sign-in, so that sign-in is spent.
    assert passport not in oauth._STATES


def test_launch_with_a_correctly_signed_but_non_hex_token_persists_nothing(client):
    # The signature is what finds the pending sign-in; the middle segment still
    # has to look like a wstoken before it is validated or stored.
    fake_sync = FakeMoodleSync()
    moodle_sync.configure(fake_sync)
    fake = FakeMoodleProvider()
    providers.configure([fake])
    passport = _issue_passport(client)

    res = _launch(client, _blob(passport, wstoken="not-a-wstoken"))

    assert res.status_code == 400
    assert fake.site_info_calls == []      # never even offered to Moodle
    assert _moodle_accounts() == []
    assert fake_sync.calls == 0


def test_launch_burns_only_the_matching_pending_sign_in(client):
    # Two sign-ins started (e.g. the user clicked twice); the returning blob
    # must consume its own and leave the other usable.
    moodle_sync.configure(FakeMoodleSync())
    providers.configure([FakeMoodleProvider()])
    first = _issue_passport(client)
    second = _issue_passport(client)

    res = _launch(client, _blob(first))

    assert res.status_code == 200
    assert first not in oauth._STATES
    assert second in oauth._STATES


def test_launch_matches_when_the_base_url_carries_a_trailing_slash(client, monkeypatch):
    # Moodle signs with its own $CFG->wwwroot, which never has a trailing
    # slash. A locally-configured base URL that does must not turn every
    # sign-in into a clueless "expired or invalid".
    monkeypatch.setattr(settings, "moodle_base_url", settings.moodle_base_url + "/")
    moodle_sync.configure(FakeMoodleSync())
    fake = FakeMoodleProvider()
    providers.configure([fake])
    passport = _issue_passport(client)
    signature = hashlib.md5(
        (settings.moodle_base_url.rstrip("/") + passport).encode()
    ).hexdigest()
    blob = base64.b64encode(f"{signature}:::{WSTOKEN}".encode()).decode()

    res = _launch(client, blob)

    assert res.status_code == 200
    assert fake.site_info_calls == [WSTOKEN]
    assert _moodle_accounts()[0]["status"] == "connected"


def test_launch_without_a_registered_moodle_provider_renders_the_error_page(client):
    moodle_sync.configure(FakeMoodleSync())
    providers.configure([FakeMoodleProvider()])
    passport = _issue_passport(client)
    providers.configure([])          # provider gone before the browser returns

    res = _launch(client, _blob(passport))

    assert res.status_code == 400
    assert _moodle_accounts() == []
    # The signature matched, so the sign-in is spent either way.
    assert passport not in oauth._STATES


@pytest.mark.parametrize("body", [
    {},                                            # no token at all
    {"token": ""},                                 # blank token
    {"token": "not-base64!!"},                     # undecodable
    # decodes fine, but carries no ':::' — no signature to match on
    {"token": base64.b64encode(b"no-separators-here").decode()},
])
def test_launch_with_a_malformed_token_is_rejected(client, body):
    fake_sync = FakeMoodleSync()
    moodle_sync.configure(fake_sync)
    providers.configure([FakeMoodleProvider()])
    passport = _issue_passport(client)

    res = client.post("/auth/moodle/launch", json=body)

    assert res.status_code == 400
    assert "text/html" in res.headers["content-type"]
    assert _moodle_accounts() == []
    assert fake_sync.calls == 0
    assert passport in oauth._STATES     # nothing matched, nothing burned


def test_launch_sync_failure_does_not_flip_a_successful_connect(client):
    fake_sync = FakeMoodleSync(boom=True)
    moodle_sync.configure(fake_sync)
    providers.configure([FakeMoodleProvider()])

    res = _launch(client, _blob(_issue_passport(client)))

    assert res.status_code == 200
    assert "Connected" in res.text
    assert fake_sync.calls == 1
    assert _moodle_accounts()[0]["status"] == "connected"


def test_launch_never_leaks_the_blob_or_the_tokens_to_responses_or_logs(client, caplog):
    caplog.set_level(logging.INFO)
    moodle_sync.configure(FakeMoodleSync())
    providers.configure([FakeMoodleProvider()])
    good_blob = _blob(_issue_passport(client))
    bad_blob = _blob("never-issued")

    ok = _launch(client, good_blob)
    bad = _launch(client, bad_blob)
    status = client.get("/api/oauth/status")
    connectors = client.get("/api/connectors")

    assert ok.status_code == 200 and bad.status_code == 400
    assert status.status_code == 200 and connectors.status_code == 200
    # Everything the APP logged. TestClient's own httpx logger echoes the
    # request line at INFO — that is the test harness, not us.
    app_logs = "\n".join(
        r.getMessage() for r in caplog.records
        if not r.name.startswith(("httpx", "httpcore"))
    )
    # App logging is genuinely being captured, so the absences below mean
    # something (this is the outcome category the mismatch above logs).
    assert "no pending sign-in matched" in app_logs
    for label, text in (
        ("success page", ok.text), ("error page", bad.text),
        ("oauth status", status.text), ("connectors", connectors.text),
        ("logs", app_logs),
    ):
        assert good_blob not in text, label
        assert bad_blob not in text, label
        assert WSTOKEN not in text, label
        assert PRIVATETOKEN not in text, label
