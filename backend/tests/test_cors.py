"""M9 Connectors / M8 Ship: the packaged Tauri webview loads from a custom-
protocol origin (macOS `tauri://localhost`; Windows/Linux `http://tauri.localhost`)
and calls the sidecar over `http://127.0.0.1:<port>`. That is a cross-origin
fetch, and every api.js request sets `Content-Type: application/json`, which
forces a CORS preflight even on GETs. If the backend's allow-list omits the
webview origin, WKWebView blocks every call and the Connectors panel (which
surfaces the failure loudly, unlike the other screens' silent empty fallback)
shows a load error. These tests pin that the webview origins are allowed while
an arbitrary origin is still rejected.
"""


def test_tauri_macos_origin_preflight_allowed(client):
    res = client.options(
        "/api/connectors",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_tauri_windows_linux_origin_preflight_allowed(client):
    res = client.options(
        "/api/connectors",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_tauri_origin_actual_request_reflects_acao(client):
    res = client.get("/api/connectors", headers={"Origin": "tauri://localhost"})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_dev_origin_still_allowed(client):
    """The Vite dev origin must keep working — the fix adds origins, never removes."""
    res = client.get("/api/connectors", headers={"Origin": "http://localhost:5173"})
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_unknown_origin_still_rejected(client):
    """The fix must not open CORS to the world: an unrelated origin gets no ACAO."""
    res = client.options(
        "/api/connectors",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res.headers.get("access-control-allow-origin") is None
