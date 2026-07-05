"""M6 provider core (§C): _flatten PHP-array encoding, the _call web-service
seam (token override + HTTP-200-exception check mapping to MoodleAuthError vs
MoodleError), the pure helpers, and registry membership."""
import base64
import hashlib
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
    parse_pasted_token,
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


# ---- parse_pasted_token ----
def test_parse_bare_32_hex_token_passthrough():
    tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"   # 32 hex chars, live-verified format
    assert parse_pasted_token(tok) == tok
    # surrounding whitespace is tolerated
    assert parse_pasted_token("  " + tok + "\n") == tok


def test_parse_launch_url_decodes_and_verifies_passport():
    wwwroot = "https://moodle-courses2527.wolfware.ncsu.edu"
    passport = "0.123456789"
    tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"
    signature = hashlib.md5((wwwroot + passport).encode()).hexdigest()
    raw = signature + ":::" + tok
    b64 = base64.b64encode(raw.encode()).decode()
    launch = "moodlemobile://token=" + b64

    parsed = parse_pasted_token(launch, passport=passport, wwwroot=wwwroot)
    assert parsed == tok


def test_parse_launch_url_with_private_token_segment():
    wwwroot = "https://moodle-courses2527.wolfware.ncsu.edu"
    passport = "0.5"
    tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"
    priv = "CKjkasuZ8GQOveWdWzBa3p7MDlh4Y1MYAN2jkDJQddHHjPZZvKTYPm5TQpTuFCmX"
    signature = hashlib.md5((wwwroot + passport).encode()).hexdigest()
    raw = signature + ":::" + tok + ":::" + priv
    launch = "moodlemobile://token=" + base64.b64encode(raw.encode()).decode()

    # token segment is the SECOND field, private token is ignored
    assert parse_pasted_token(launch, passport=passport, wwwroot=wwwroot) == tok


def test_parse_launch_url_bad_passport_raises():
    wwwroot = "https://moodle-courses2527.wolfware.ncsu.edu"
    tok = "e5ed213ed9bb87e21c0cb1e4e71d174c"
    # signature computed with the WRONG passport -> md5 prefix won't match
    wrong_sig = hashlib.md5((wwwroot + "9.9").encode()).hexdigest()
    raw = wrong_sig + ":::" + tok
    launch = "app://token=" + base64.b64encode(raw.encode()).decode()
    with pytest.raises(MoodleError):
        parse_pasted_token(launch, passport="0.1", wwwroot=wwwroot)


def test_parse_unrecognized_raises_moodle_error():
    with pytest.raises(MoodleError):
        parse_pasted_token("not a token")


# ---- get_site_info ----
def test_get_site_info_maps_functions_to_name_list():
    http = FakeMoodleHTTP(payloads={"core_webservice_get_site_info": {
        "userid": 56,
        "fullname": "Wolf Pack",
        "sitename": "WolfWare",
        "release": "4.5.1 (Build: 20250113)",
        "functions": [
            {"name": "core_enrol_get_users_courses", "version": "4.5"},
            {"name": "mod_assign_get_assignments", "version": "4.5"},
        ],
    }})
    info = _provider(http).get_site_info("pasted-token")
    assert info == {
        "userid": 56,
        "sitename": "WolfWare",
        "release": "4.5.1 (Build: 20250113)",
        "functions": ["core_enrol_get_users_courses", "mod_assign_get_assignments"],
    }
    # the pasted token was used as the wstoken (override), not the injected one
    _, data = http.posts[-1]
    assert data["wstoken"] == "pasted-token"
    assert data["wsfunction"] == "core_webservice_get_site_info"


def test_get_site_info_auth_failure_raises_moodle_auth_error():
    http = FakeMoodleHTTP(exceptions={"core_webservice_get_site_info": {
        "exception": "moodle_exception", "errorcode": "invalidtoken",
        "message": "Invalid token",
    }})
    with pytest.raises(MoodleAuthError):
        _provider(http).get_site_info("bad-token")
