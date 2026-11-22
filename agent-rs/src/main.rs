#![windows_subsystem = "windows"]

mod panel;
mod tray;
mod worker;
mod win;

fn main() {
    win::set_dpi_aware();
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(|s| s.as_str()) == Some("worker") {
        if let Err(e) = worker::run_worker() { win::log(&format!("worker error: {e:#}")); }
        return;
    }
    if !win::single_instance("DoudianRemoteQR.Panel") {
        open::that("http://127.0.0.1:8765/").ok();
        return;
    }
    if let Err(e) = panel::start_server() {
        win::log(&format!("panel error: {e:#}"));
        return;
    }
    open::that("http://127.0.0.1:8765/").ok();
    tray::run_tray();
}
