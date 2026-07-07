// Prevents an extra console window on Windows (no-op on macOS); standard Tauri stub.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    scuffedos_lib::run()
}
