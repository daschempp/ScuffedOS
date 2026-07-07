// scuffedos-backend: the Tauri externalBin. A single-file stub whose only job
// is to exec the vendored CPython running uvicorn, with cwd at the bundled
// backend source. It rides next to a multi-file Python tree that cannot itself
// be the sidecar.
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    // current_exe() = .../Contents/MacOS/scuffedos-backend
    let exe = std::env::current_exe().expect("current_exe");
    // .../Contents/MacOS -> .../Contents
    let contents = exe
        .parent()
        .and_then(|p| p.parent())
        .expect("Contents dir")
        .to_path_buf();
    let resources: PathBuf = contents.join("Resources");
    let python = resources.join("py").join("bin").join("python3");
    let backend = resources.join("backend");

    // Pass our args straight through (Rust sends: --port <digits>).
    let args: Vec<String> = std::env::args().skip(1).collect();

    let err = Command::new(python)
        .current_dir(&backend)
        .arg("-m")
        .arg("uvicorn")
        .arg("app.main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .args(&args) // forwards --port <p>
        // SCUFFEDOS_MANAGED_PG / RESOURCES_PGSQL_DIR are inherited from the
        // parent (the Rust shell set them on spawn); no need to re-set here.
        .exec(); // replaces this process on success; only returns on error

    eprintln!("scuffedos-backend: failed to exec python: {err}");
    std::process::exit(1);
}
