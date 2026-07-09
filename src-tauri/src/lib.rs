use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Manager, RunEvent, State, WindowEvent};
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
