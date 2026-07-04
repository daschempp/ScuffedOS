"""M6 provider core (§C): _flatten PHP-array encoding, the _call web-service
seam (token override + HTTP-200-exception check mapping to MoodleAuthError vs
MoodleError), the pure helpers, and registry membership."""
from datetime import datetime, timezone

import pytest

from app import providers
from app.providers.base import Tokens
from app.providers.moodle import (
    MoodleAuthError,
    MoodleError,
    MoodleProvider,
    _epoch,
    _flatten,
    _strip_html,
)

from .fakes import FakeMoodleHTTP


def _provider(http, *, token: str = "tok123") -> MoodleProvider:
    p = MoodleProvider()
    p.configure(http)
    p.set_tokens(Tokens(access_token=token, refresh_token=None, expires_at=None,
                        scopes="", provider_user_id="56"))
    return p


# ---- _flatten (PHP-array param encoding) ----
def test_flatten_list_produces_indexed_keys():
    out = _flatten({"courseids": [72, 69]})
    assert out == {"courseids[0]": "72", "courseids[1]": "69"}


def test_flatten_scalars_stringified():
    out = _flatten({"userid": 56, "newestfirst": 1})
    assert out == {"userid": "56", "newestfirst": "1"}


def test_flatten_nested_dict_recurses():
    out = _flatten({"options": {"ids": [1, 2]}})
    assert out == {"options[ids][0]": "1", "options[ids][1]": "2"}


# ---- _call ----
def test_call_posts_token_wsfunction_and_flattened_params():
    http = FakeMoodleHTTP(payloads={"core_enrol_get_users_courses": [{"id": 72}]})
    p = _provider(http)
    out = p._call("core_enrol_get_users_courses", userid=56)
    assert out == [{"id": 72}]
    url, data = http.posts[-1]
    assert url.endswith("/webservice/rest/server.php")
    assert data["wstoken"] == "tok123"
    assert data["wsfunction"] == "core_enrol_get_users_courses"
    assert data["moodlewsrestformat"] == "json"
    assert data["userid"] == "56"


def test_call_token_override_wins_over_injected_tokens():
    http = FakeMoodleHTTP(payloads={"core_webservice_get_site_info": {"userid": 56}})
    p = _provider(http, token="injected")
    p._call("core_webservice_get_site_info", token="pasted-token")
    _, data = http.posts[-1]
    assert data["wstoken"] == "pasted-token"


def test_call_raises_moodle_auth_error_on_invalidtoken():
    http = FakeMoodleHTTP(exceptions={"core_webservice_get_site_info": {
        "exception": "moodle_exception", "errorcode": "invalidtoken",
        "message": "Invalid token - token not found",
    }})
    with pytest.raises(MoodleAuthError):
        _provider(http)._call("core_webservice_get_site_info")


def test_call_raises_moodle_error_on_non_auth_exception():
    http = FakeMoodleHTTP(exceptions={"mod_assign_get_assignments": {
        "exception": "webservice_access_exception", "errorcode": "nofunction",
        "message": "Function not found",
    }})
    with pytest.raises(MoodleError) as ei:
        _provider(http)._call("mod_assign_get_assignments")
    assert not isinstance(ei.value, MoodleAuthError)


# ---- pure helpers ----
def test_epoch_maps_seconds_to_aware_utc_and_zero_to_none():
    dt = _epoch(1_782_777_540)
    assert dt is not None and dt.tzinfo is timezone.utc
    assert dt == datetime(2026, 6, 29, 23, 59, tzinfo=timezone.utc)
    assert _epoch(0) is None and _epoch(None) is None and _epoch("") is None


def test_strip_html_drops_tags_and_collapses_whitespace():
    assert _strip_html("<p>Hello &amp; <b>welcome</b></p>") == "Hello & welcome"
    assert _strip_html("<script>x=1</script>Body") == "Body"
    assert _strip_html("") == ""


# ---- registry membership ----
def test_moodle_provider_registered_in_all_providers():
    providers.configure("unset")  # real registry (conftest installs [] for tests)
    try:
        names = {p.name for p in providers.all_providers()}
    finally:
        providers.configure([])   # restore the test-time empty registry
    assert "moodle" in names
