use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, State, WindowEvent};
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

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![api_port])
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
                        let _ = show_handle.emit("api-port", port);
                    }
                } else {
                    eprintln!("[shell] health-gate timed out on :{port}; backend did not become ready");
                    // Minimal diagnostic: still show the window so the user isn't
                    // stuck on a blank hidden app; frontend shows its own error UI.
                    if let Some(win) = show_handle.get_webview_window("main") {
                        let _ = win.show();
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // On macOS, closing the window does not quit the app by default.
            if let WindowEvent::CloseRequested { .. } = event {
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
                    let _ = child.kill(); // polite: lets the Python atexit run pg_ctl stop
                    kill_process_tree(pid); // backstop: reap any orphaned postgres
                }
            }
        });
}
