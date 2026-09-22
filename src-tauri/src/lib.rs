use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Manager, RunEvent, State, WindowEvent};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Shared handle to the spawned backend child + the chosen port.
struct Backend {
    child: Arc<Mutex<Option<CommandChild>>>,
    port: u16,
}

/// Pick a free loopback port by binding to :0 and immediately dropping the listener.
fn free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind 127.0.0.1:0");
    let port = listener.local_addr().expect("local_addr").port();
    drop(listener);
    port
}

/// Kill the sidecar's whole process tree (backstop for the Python-owned pg_ctl
/// stop). SIGTERM first, escalate to KILL after a grace period.
fn kill_process_tree(root_pid: u32) {
    use sysinfo::{Pid, ProcessesToUpdate, Signal, System};
    let mut sys = System::new();
    sys.refresh_processes(ProcessesToUpdate::All, true);

    // Collect root + all transitive descendants.
    let mut targets = vec![Pid::from_u32(root_pid)];
    let mut i = 0;
    while i < targets.len() {
        let parent = targets[i];
        for (pid, proc_) in sys.processes() {
            if proc_.parent() == Some(parent) && !targets.contains(pid) {
                targets.push(*pid);
            }
        }
        i += 1;
    }
    // SIGTERM, then a short wait, then SIGKILL survivors.
    for pid in &targets {
        if let Some(p) = sys.process(*pid) {
            let _ = p.kill_with(Signal::Term);
        }
    }
    std::thread::sleep(Duration::from_millis(1500));
    sys.refresh_processes(ProcessesToUpdate::All, true);
    for pid in &targets {
        if let Some(p) = sys.process(*pid) {
            let _ = p.kill_with(Signal::Kill);
        }
    }
}

#[tauri::command]
fn api_port(state: State<Backend>) -> u16 {
    state.port
}

/// Poll GET /health until 200 (bounded). Returns true on success.
fn wait_for_health(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/health");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(500))
        .build()
        .expect("reqwest client");
    for _ in 0..150 {
        // ~150 * 200ms = 30s ceiling (first run does initdb + alembic).
        if let Ok(resp) = client.get(&url).send() {
            if resp.status().is_success() {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

/// Longest Moodle launch blob we accept. The real thing is a couple of hundred
/// chars (`base64(md5(wwwroot+passport):::wstoken[:::privatetoken])`); this is a
/// cheap sanity bound, not a protocol limit.
const MAX_LAUNCH_BLOB_LEN: usize = 4096;

/// Extract the token blob from a Moodle sign-in launch link
/// (`scuffedos://token=<blob>` or `moodlemobile://token=<blob>`).
///
/// Matched on the raw string, not on a parsed host/path: these are non-special
/// schemes, so `url` splits `moodlemobile://token=abc/def==` into host
/// `token=abc` + path `/def==`. It round-trips verbatim, but `host_str()` alone
/// would silently truncate the blob.
///
/// `None` unless the blob is non-empty, at most `MAX_LAUNCH_BLOB_LEN` chars and
/// entirely within the standard base64 alphabet `[A-Za-z0-9+/=]` — which also
/// makes the byte length above a char count.
fn moodle_launch_blob(deep_link: &str) -> Option<&str> {
    let blob = deep_link
        .strip_prefix("scuffedos://token=")
        .or_else(|| deep_link.strip_prefix("moodlemobile://token="))?;
    let ok = !blob.is_empty()
        && blob.len() <= MAX_LAUNCH_BLOB_LEN
        && blob
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'+' | b'/' | b'='));
    ok.then_some(blob)
}

/// Map a Moodle sign-in launch deep link (`scuffedos://token=<blob>` or
/// `moodlemobile://token=<blob>`) to the loopback call the backend serves:
/// `POST http://127.0.0.1:{port}/auth/moodle/launch` with the JSON body
/// `{"token":"<blob>"}`. Returns `(url, json_body)`, or `None` for anything else
/// — which is also what rejects every non-launch `moodlemobile` link.
///
/// The blob rides in the body, never the query string. The sidecar runs uvicorn
/// with its default access log, whose request line (path *and* query) goes to
/// stdout, and `run()` below drains that stdout into our stderr as `[backend] …`
/// — so a `?token=` forward would print the whole secret on every sign-in. A
/// POST body is not access-logged.
///
/// The body is assembled with `serde_json` rather than string interpolation, and
/// `moodle_launch_blob` has already constrained the blob to `[A-Za-z0-9+/=]`, so
/// nothing in it can break out of the JSON string.
fn moodle_launch_forward(deep_link: &str, port: u16) -> Option<(String, String)> {
    let blob = moodle_launch_blob(deep_link)?;
    let url = format!("http://127.0.0.1:{port}/auth/moodle/launch");
    let body = serde_json::json!({ "token": blob }).to_string();
    Some((url, body))
}

/// Map an incoming `scuffedos://oauth/callback?provider=<p>&<oauth query>` deep
/// link to the loopback OAuth callback the backend serves:
/// `http://127.0.0.1:{port}/auth/{p}/callback?<oauth query minus provider>`,
/// fetched with a GET. The Moodle launch hop is a separate shape and a separate
/// transport; see `moodle_launch_forward`.
///
/// Returns `None` for anything that is not our exact scheme/host/path, or whose
/// `provider` is missing/empty/not lowercase-ascii (a path-injection guard — the
/// segment is interpolated into the URL path). The backend's one-time CSRF state
/// check is the real authorization gate; this is defense in depth.
fn forward_target_url(deep_link: &str, port: u16) -> Option<String> {
    let url = reqwest::Url::parse(deep_link).ok()?;
    if url.scheme() != "scuffedos" {
        return None;
    }
    // `scuffedos://oauth/callback` parses to host "oauth", path "/callback".
    if url.host_str() != Some("oauth") || url.path() != "/callback" {
        return None;
    }

    let pairs: Vec<(String, String)> = url.query_pairs().into_owned().collect();
    let provider = pairs
        .iter()
        .find(|(k, _)| k == "provider")
        .map(|(_, v)| v.clone())
        .filter(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_lowercase()))?;

    let mut target =
        reqwest::Url::parse(&format!("http://127.0.0.1:{port}/auth/{provider}/callback")).ok()?;
    {
        let mut qp = target.query_pairs_mut();
        for (k, v) in pairs.iter().filter(|(k, _)| k != "provider") {
            qp.append_pair(k, v);
        }
    }
    // Drop the trailing "?" url writes when there are no pairs.
    Some(match target.query() {
        Some("") | None => {
            target.set_query(None);
            target.to_string()
        }
        Some(_) => target.to_string(),
    })
}

/// Everything after `<scheme>:`, with the optional `//` authority marker
/// removed. Works for cannot-be-a-base URLs (`scuffedos:token=…`, no authority,
/// so no host at all) as well as the usual `scheme://…` form.
fn after_scheme(url_str: &str) -> &str {
    let rest = url_str.split_once(':').map_or("", |(_, rest)| rest);
    rest.strip_prefix("//").unwrap_or(rest)
}

/// Render a deep link for logging with its secrets removed. Default-DENY: a
/// shape we do not positively recognize is collapsed, not printed.
///
/// A rejected link still carries live credentials, and where they sit depends on
/// the shape — an OAuth callback hides its code and state in the query, while a
/// Moodle launch link is secret from the first character after the scheme. So:
///
/// * anything whose post-scheme text begins with `token` — any case, `=` literal
///   or percent-encoded, `//` present or not — becomes `<scheme>://token=<redacted>`;
/// * the one recognized OAuth shape prints as `scuffedos://oauth/callback`;
/// * everything else becomes `<scheme>://<redacted>`, because an unknown shape
///   may carry a secret in its host or path just as easily as in its query.
///
/// Only the scheme is ever echoed verbatim, and `url` has already normalized
/// that to a lowercase ASCII token.
fn redact_deep_link(url: &reqwest::Url) -> String {
    let scheme = url.scheme();
    let rest = after_scheme(url.as_str());
    if rest.get(..5).is_some_and(|p| p.eq_ignore_ascii_case("token")) {
        return format!("{scheme}://token=<redacted>");
    }
    // `scuffedos://oauth/callback` parses to host "oauth", path "/callback".
    if scheme == "scuffedos" && url.host_str() == Some("oauth") && url.path() == "/callback" {
        return "scuffedos://oauth/callback".to_string();
    }
    format!("{scheme}://<redacted>")
}

/// Resolve ~/Library/Application Support/ScuffedOS/logs/<name>.
fn app_log_path(name: &str) -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    std::path::PathBuf::from(home)
        .join("Library")
        .join("Application Support")
        .join("ScuffedOS")
        .join("logs")
        .join(name)
}

/// Return the last `max_bytes` of a UTF-8 log file (or a placeholder if absent).
fn tail_file(path: &std::path::Path, max_bytes: usize) -> String {
    match std::fs::read(path) {
        Ok(bytes) => {
            let start = bytes.len().saturating_sub(max_bytes);
            String::from_utf8_lossy(&bytes[start..]).into_owned()
        }
        Err(_) => format!("(no log at {})", path.display()),
    }
}

/// HTML-escape for safe interpolation into the inline diagnostic page.
fn html_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// Open a diagnostic window surfacing the backend + pg log tails on a
/// health-gate timeout, instead of a blank hidden main window (spec §6).
///
/// The health-gate timeout is one-shot, but guard against a double-open anyway:
/// if a "diagnostic" window already exists (e.g. a future retry path), focus it
/// instead of stacking a second identical window.
///
/// Delivery: the HTML is written to a temp file and loaded via a `file:` URL
/// (`WebviewUrl::External`). `http`, `https`, and `file:` URLs are all accepted
/// via `WebviewUrl::External` without any feature gate. Only `data:` URLs are
/// gated behind the `webview-data-url` Cargo feature (not enabled here), so
/// `WebviewUrl::App("data:…")` / any `data:` scheme is rejected at runtime by
/// `prepare_webview` (tauri-2.11.5/src/manager/webview.rs:477-482 →
/// `Err(InvalidWebviewUrl(..))`). The `file:` scheme reaches no such gate and
/// flows through `WebviewUrl::External` (webview.rs:462-471) to the success
/// path (`pending.url = url.to_string()`, webview.rs:500).
///
/// The temp HTML file is deliberately NOT removed right after `.build()`
/// returns: the webview loads the `file:` URL asynchronously, so an inline
/// delete here would race that load and could blank the window. Cleanup
/// instead happens in the `on_window_event` handler below, keyed off this
/// window's label, once the diagnostic window actually closes.
fn show_diagnostic_window(app: &tauri::AppHandle, backend_tail: &str, pg_tail: &str) {
    use tauri::Manager;
    if let Some(existing) = app.get_webview_window("diagnostic") {
        let _ = existing.set_focus();
        return;
    }
    let html = format!(
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>ScuffedOS — startup problem</title>\
         <style>body{{font:13px -apple-system,system-ui,sans-serif;margin:0;padding:20px;background:#1c1b19;color:#e8e4dd}}\
         h1{{font-size:18px;margin:0 0 4px}}p{{color:#b8b2a7;margin:0 0 16px}}\
         h2{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#8a8578;margin:18px 0 6px}}\
         pre{{background:#111;border:1px solid #333;border-radius:6px;padding:12px;overflow:auto;max-height:32vh;white-space:pre-wrap;word-break:break-word}}\
         button{{margin-top:18px;padding:8px 16px;border:0;border-radius:6px;background:#c4552e;color:#fff;font-size:13px;cursor:pointer}}</style></head>\
         <body><h1>ScuffedOS didn't finish starting</h1>\
         <p>The backend did not become ready in time. The logs below may explain why.</p>\
         <h2>backend.log</h2><pre>{}</pre>\
         <h2>pg.log</h2><pre>{}</pre>\
         <button onclick=\"window.__TAURI_INTERNALS__.invoke('quit_app')\">Quit</button>\
         </body></html>",
        html_escape(backend_tail),
        html_escape(pg_tail),
    );

    // Write the page to a temp file and load it via a file: URL. If the write or
    // URL construction fails, fall back to showing the main window so the user
    // is never left staring at nothing.
    let html_path = std::env::temp_dir().join("scuffedos-startup-problem.html");
    let url = match std::fs::write(&html_path, html.as_bytes())
        .map_err(|e| format!("write diagnostic HTML to {}: {e}", html_path.display()))
        .and_then(|()| {
            tauri::Url::from_file_path(&html_path)
                .map_err(|()| format!("build file: URL from {}", html_path.display()))
        }) {
        Ok(url) => url,
        Err(e) => {
            eprintln!("[shell] failed to prepare diagnostic window: {e}");
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
            }
            return;
        }
    };

    if let Err(e) = tauri::WebviewWindowBuilder::new(app, "diagnostic", tauri::WebviewUrl::External(url))
        .title("ScuffedOS — startup problem")
        .inner_size(720.0, 560.0)
        .build()
    {
        eprintln!("[shell] failed to open diagnostic window: {e}");
        // Last-resort fallback: surface the main window rather than nothing.
        if let Some(win) = app.get_webview_window("main") {
            let _ = win.show();
        }
    }
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_deep_link::init())
        .invoke_handler(tauri::generate_handler![api_port, quit_app])
        .setup(|app| {
            let port = free_port();

            // Spawn the sidecar with the managed-PG env so the Python side owns
            // Postgres and injects the socket DSN itself.
            let resource_dir = app.path().resource_dir()?;
            let pgsql_res = resource_dir.join("pgsql");
            let (mut rx, child) = app
                .shell()
                .sidecar("scuffedos-backend")?
                .env("SCUFFEDOS_MANAGED_PG", "1")
                .env("RESOURCES_PGSQL_DIR", pgsql_res.to_string_lossy().to_string())
                .env("SCUFFEDOS_PORT", port.to_string())
                .args(["--port", &port.to_string()])
                .spawn()?;

            let child = Arc::new(Mutex::new(Some(child)));
            app.manage(Backend { child: child.clone(), port });

            // Forward recognized deep links into the loopback endpoints the
            // backend serves. The plugin delivers these here, including the
            // cold-start launch URL (macOS buffers it and replays it to
            // on_open_url). Two hops ride this channel:
            //
            //   * WHOOP OAuth callback (`scuffedos://oauth/callback?…`). WHOOP
            //     needs a public https redirect (its dashboard rejects
            //     loopback), so the public bounce page hops the code back in
            //     via this scheme.
            //   * Moodle sign-in launch (`scuffedos://token=<blob>`, or
            //     `moodlemobile://token=<blob>` when the site forces the
            //     official app's scheme). Moodle redirects the browser here
            //     with the signed token blob once the user has signed in. This
            //     one POSTs the blob as a JSON body so it never reaches the
            //     backend's access log — and from there our stderr drain.
            //
            // The backend's one-time state check rejects any forged deep link,
            // so firing for any recognized incoming URL is safe.
            let dl_handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                let port = dl_handle.state::<Backend>().port;
                for url in event.urls() {
                    // A POST body for the Moodle launch, a plain GET for the
                    // OAuth callback. The launch shape is checked first; the two
                    // never both match.
                    let forward = moodle_launch_forward(url.as_str(), port)
                        .map(|(target, body)| (target, Some(body)))
                        .or_else(|| forward_target_url(url.as_str(), port).map(|t| (t, None)));
                    match forward {
                        Some((target, body)) => {
                            let h = dl_handle.clone();
                            std::thread::spawn(move || {
                                // Gate on backend health BEFORE the single
                                // forward: on a cold start the sidecar may not be
                                // listening yet. The state token is one-time, so
                                // we must NOT retry the request itself — wait
                                // health, then fire exactly once. reqwest::blocking
                                // must run off the UI/tokio thread (mirrors the
                                // health-gate worker at lib.rs:239).
                                if !wait_for_health(h.state::<Backend>().port) {
                                    eprintln!("[deep-link] backend not healthy; dropping forward");
                                    return;
                                }
                                let client = reqwest::blocking::Client::builder()
                                    .timeout(Duration::from_secs(30))
                                    .build()
                                    .expect("reqwest client");
                                let req = match body {
                                    Some(json) => client
                                        .post(&target)
                                        .header("content-type", "application/json")
                                        .body(json),
                                    None => client.get(&target),
                                };
                                match req.send() {
                                    Ok(resp) => eprintln!("[deep-link] forwarded deep link ({})", resp.status()),
                                    // without_url(): reqwest's Display appends the
                                    // request URL, which carries the live OAuth
                                    // code and state. Keep it out of the log. (The
                                    // launch blob is in the body, which Display
                                    // never touches.)
                                    Err(e) => eprintln!("[deep-link] deep link forward failed: {}", e.without_url()),
                                }
                            });
                        }
                        None => {
                            // Log the shape of the rejected link, never its
                            // secrets: a malformed callback still carries a live
                            // code/state, and a launch link is all secret.
                            eprintln!(
                                "[deep-link] ignoring unrecognized deep link: {}",
                                redact_deep_link(&url)
                            );
                        }
                    }
                }
            });

            // Drain the sidecar's stdout/stderr to the console (app log).
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Stderr(bytes) => {
                            eprintln!("[backend:err] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] terminated: {:?}", payload);
                        }
                        _ => {}
                    }
                }
                let _ = &app_handle;
            });

            // Health-gate on a worker thread, then show (or surface an error).
            let show_handle = app.handle().clone();
            std::thread::spawn(move || {
                if wait_for_health(port) {
                    if let Some(win) = show_handle.get_webview_window("main") {
                        let _ = win.show();
                    }
                } else {
                    eprintln!("[shell] health-gate timed out on :{port}; showing diagnostic window");
                    let backend_tail = tail_file(&app_log_path("backend.log"), 8192);
                    let pg_tail = tail_file(&app_log_path("pg.log"), 8192);
                    show_diagnostic_window(&show_handle, &backend_tail, &pg_tail);
                    // Do NOT show the blank main window; the diagnostic replaces it.
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                // The diagnostic window's HTML is loaded from a temp file (see
                // show_diagnostic_window); clean it up now that the window is
                // actually closing, rather than racing the async file: load by
                // removing it right after .build().
                if window.label() == "diagnostic" {
                    let html_path = std::env::temp_dir().join("scuffedos-startup-problem.html");
                    let _ = std::fs::remove_file(html_path);
                }
                // On macOS, closing the window does not quit the app by default.
                window.app_handle().exit(0);
            }
        })
        .build(tauri::generate_context!())
        .expect("error building ScuffedOS")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                let state: State<Backend> = app_handle.state();
                let maybe_child = state.child.lock().unwrap().take();
                if let Some(child) = maybe_child {
                    let pid = child.pid();
                    // SIGTERM the whole tree (Python + its still-parented postgres)
                    // first, so Python's atexit/SIGTERM handler can run `pg_ctl
                    // stop -m fast` and shut Postgres down cleanly; survivors get
                    // SIGKILL after a grace period. Do NOT call child.kill() here:
                    // that sends an uncatchable SIGKILL that would (a) skip the
                    // Python handler entirely and (b) let Postgres re-parent to
                    // launchd before we've captured it in the process-tree
                    // snapshot below. CommandChild has no custom Drop impl (it
                    // just holds an Arc<SharedChild> + a pipe writer), so letting
                    // `child` drop after the tree-kill is a no-op — it does not
                    // send any signal.
                    kill_process_tree(pid);
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{forward_target_url, moodle_launch_forward, redact_deep_link};

    #[test]
    fn maps_whoop_callback_to_loopback_preserving_code_and_state() {
        let got = forward_target_url(
            "scuffedos://oauth/callback?provider=whoop&code=abc123&state=xyz789",
            54321,
        );
        assert_eq!(
            got.as_deref(),
            Some("http://127.0.0.1:54321/auth/whoop/callback?code=abc123&state=xyz789"),
        );
    }

    #[test]
    fn preserves_error_param_and_reencodes_values() {
        // WHOOP denial: error present, no code. query_pairs decodes `a+b` to
        // "a b"; append_pair re-encodes the space back to `+`.
        let got = forward_target_url(
            "scuffedos://oauth/callback?provider=whoop&error=access_denied&state=a+b",
            8000,
        );
        assert_eq!(
            got.as_deref(),
            Some("http://127.0.0.1:8000/auth/whoop/callback?error=access_denied&state=a+b"),
        );
    }

    #[test]
    fn rejects_foreign_scheme() {
        assert_eq!(
            forward_target_url("https://evil.example/oauth/callback?provider=whoop&code=x", 8000),
            None,
        );
    }

    #[test]
    fn rejects_wrong_host_or_path() {
        assert_eq!(
            forward_target_url("scuffedos://evil/callback?provider=whoop&code=x", 8000),
            None,
        );
        assert_eq!(
            forward_target_url("scuffedos://oauth/other?provider=whoop&code=x", 8000),
            None,
        );
    }

    #[test]
    fn rejects_missing_empty_or_unsafe_provider() {
        assert_eq!(
            forward_target_url("scuffedos://oauth/callback?code=x&state=y", 8000),
            None,
        );
        assert_eq!(
            forward_target_url("scuffedos://oauth/callback?provider=&code=x", 8000),
            None,
        );
        // Path-injection defense: provider must be lowercase ascii only.
        assert_eq!(
            forward_target_url("scuffedos://oauth/callback?provider=..%2Fetc&code=x", 8000),
            None,
        );
    }

    // ---- Moodle launch hop: `<scheme>://token=<blob>` ----

    /// The forward the launch hop must produce: a POST that keeps the blob out
    /// of the request line (and so out of the backend's access log).
    fn want_launch(port: u16) -> Option<(String, String)> {
        Some((
            format!("http://127.0.0.1:{port}/auth/moodle/launch"),
            r#"{"token":"YWJj+/ZGVm=="}"#.to_string(),
        ))
    }

    #[test]
    fn maps_scuffedos_launch_token_to_a_post_with_a_json_body() {
        assert_eq!(
            moodle_launch_forward("scuffedos://token=YWJj+/ZGVm==", 54321),
            want_launch(54321),
        );
    }

    #[test]
    fn maps_moodlemobile_launch_token_to_a_post_with_a_json_body() {
        // Sites that force the official app's scheme redirect to moodlemobile://.
        assert_eq!(
            moodle_launch_forward("moodlemobile://token=YWJj+/ZGVm==", 8000),
            want_launch(8000),
        );
    }

    #[test]
    fn launch_forward_never_puts_the_blob_in_the_url() {
        // The whole point of the POST: a query string would land in uvicorn's
        // access log, which the sidecar drain re-emits to our stderr.
        let (url, body) = moodle_launch_forward("scuffedos://token=YWJj+/ZGVm==", 8000).unwrap();
        assert!(!url.contains("YWJj"), "blob leaked into the URL: {url}");
        assert!(!url.contains('?'), "launch forward must have no query: {url}");
        assert!(body.contains("YWJj+/ZGVm=="), "body must carry the raw blob");
    }

    #[test]
    fn maps_launch_link_after_a_url_parse_round_trip() {
        // The handler hands us `url.as_str()` from the deep-link plugin's parsed
        // `Url`, so pin that the blob survives parse + reserialize untouched —
        // raw-string inputs alone would not catch the url crate re-encoding it.
        let url = reqwest::Url::parse("moodlemobile://token=YWJj+/ZGVm==").unwrap();
        assert_eq!(moodle_launch_forward(url.as_str(), 8000), want_launch(8000));
    }

    #[test]
    fn rejects_empty_launch_blob() {
        assert_eq!(moodle_launch_forward("scuffedos://token=", 8000), None);
        assert_eq!(moodle_launch_forward("moodlemobile://token=", 8000), None);
    }

    #[test]
    fn rejects_launch_blob_outside_base64_alphabet() {
        assert_eq!(
            moodle_launch_forward("scuffedos://token=YWJj?ZGVm", 8000),
            None
        );
        assert_eq!(
            moodle_launch_forward("scuffedos://token=YWJj ZGVm", 8000),
            None
        );
        assert_eq!(
            moodle_launch_forward("moodlemobile://token=YWJj%2FZGVm", 8000),
            None
        );
        // The alphabet check is also what keeps the hand-built JSON body safe.
        assert_eq!(
            moodle_launch_forward(r#"scuffedos://token=a","x":"b"#, 8000),
            None
        );
    }

    #[test]
    fn rejects_overlong_launch_blob() {
        let at_limit = "A".repeat(4096);
        assert!(moodle_launch_forward(&format!("scuffedos://token={at_limit}"), 8000).is_some());
        let too_long = "A".repeat(4097);
        assert_eq!(
            moodle_launch_forward(&format!("scuffedos://token={too_long}"), 8000),
            None,
        );
    }

    #[test]
    fn rejects_non_launch_moodlemobile_links() {
        // The moodlemobile scheme is accepted for the `token=` launch only, and
        // neither forward claims it — the handler consults both in turn.
        let link = "moodlemobile://oauth/callback?provider=whoop&code=x";
        assert_eq!(moodle_launch_forward(link, 8000), None);
        assert_eq!(forward_target_url(link, 8000), None);
    }

    #[test]
    fn the_two_forwards_do_not_overlap() {
        // A launch link must never fall through into the OAuth GET branch.
        assert_eq!(forward_target_url("scuffedos://token=YWJj+/ZGVm==", 8000), None);
        assert_eq!(
            moodle_launch_forward("scuffedos://oauth/callback?provider=whoop&code=x", 8000),
            None,
        );
    }

    // ---- Logging redaction ----

    #[test]
    fn redact_deep_link_hides_the_launch_blob() {
        // Default-deny: detection must not hinge on the exact lowercase spelling
        // of `token`, on the `=` being literal rather than percent-encoded, or on
        // the `//` being present (a cannot-be-a-base URL has no host at all).
        for raw in [
            "moodlemobile://token=YWJj/ZGVm==",
            "scuffedos://token=YWJj/ZGVm==",
            "scuffedos://TOKEN=YWJj/ZGVm==",
            "scuffedos://token%3DYWJj/ZGVm==",
            "scuffedos:token=YWJj/ZGVm==",
        ] {
            let url = reqwest::Url::parse(raw).unwrap();
            let want = format!("{}://token=<redacted>", url.scheme());
            let got = redact_deep_link(&url);
            assert_eq!(got, want, "for {raw}");
            assert!(!got.contains("YWJj"), "blob leaked for {raw}: {got}");
        }
    }

    #[test]
    fn redact_deep_link_allows_only_the_oauth_callback_shape() {
        // The one recognized shape keeps scheme+host+path; its query is dropped.
        let url = reqwest::Url::parse("scuffedos://oauth/callback?provider=whoop&code=x").unwrap();
        assert_eq!(redact_deep_link(&url), "scuffedos://oauth/callback");
        // Anything else is redacted wholesale rather than printed: an unknown
        // shape may carry a secret anywhere, including the host and path.
        let url = reqwest::Url::parse("scuffedos://YWJj/ZGVm?x=1").unwrap();
        assert_eq!(redact_deep_link(&url), "scuffedos://<redacted>");
        let url = reqwest::Url::parse("https://evil.example/p?code=YWJj").unwrap();
        assert_eq!(redact_deep_link(&url), "https://<redacted>");
    }
}
