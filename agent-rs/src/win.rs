use std::ffi::c_void;

#[cfg(windows)]
pub fn set_dpi_aware() {
    use windows::Win32::UI::HiDpi::{SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2};
    unsafe { SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2).ok(); }
}

#[cfg(not(windows))]
pub fn set_dpi_aware() {}

#[cfg(windows)]
pub fn process_name(pid: u32) -> String {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION};
    use windows::core::PWSTR;
    unsafe {
        let h = match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) { Ok(h) => h, Err(_) => return String::new() };
        let mut buf = [0u16; 1024];
        let mut len = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(h, PROCESS_NAME_WIN32, PWSTR(buf.as_mut_ptr()), &mut len).is_ok();
        let _ = CloseHandle(h);
        if ok { String::from_utf16_lossy(&buf[..len as usize]) } else { String::new() }
    }
}

#[cfg(not(windows))]
pub fn process_name(_pid: u32) -> String { String::new() }

#[cfg(windows)]
pub fn find_window() -> Option<isize> {
    use windows::Win32::Foundation::{BOOL, HWND, LPARAM, RECT};
    use windows::Win32::UI::WindowsAndMessaging::{EnumWindows, GetWindowRect, IsWindowVisible};
    unsafe extern "system" fn cb(hwnd: HWND, lparam: LPARAM) -> BOOL {
        if !IsWindowVisible(hwnd).as_bool() { return BOOL(1); }
        let pid = window_pid(hwnd.0 as isize);
        let name = process_name(pid).to_ascii_lowercase();
        if name.ends_with("doudian.exe") || name.contains("doudian") {
            let mut r = RECT::default();
            let _ = GetWindowRect(hwnd, &mut r);
            let area = (r.right - r.left) * (r.bottom - r.top);
            let out = lparam.0 as *mut (Option<isize>, i32);
            if area > (*out).1 { *out = (Some(hwnd.0 as isize), area); }
        }
        BOOL(1)
    }
    let mut found: (Option<isize>, i32) = (None, 0);
    unsafe { EnumWindows(Some(cb), LPARAM(&mut found as *mut _ as isize)).ok(); }
    found.0
}

#[cfg(not(windows))]
pub fn find_window() -> Option<isize> { None }

#[cfg(windows)]
pub fn window_pid(hwnd: isize) -> u32 {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::GetWindowThreadProcessId;
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(HWND(hwnd as *mut c_void), Some(&mut pid)); }
    pid
}

#[cfg(not(windows))]
pub fn window_pid(_hwnd: isize) -> u32 { 0 }

#[cfg(windows)]
pub fn restore(hwnd: isize) {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::{ShowWindow, SW_RESTORE};
    unsafe { let _ = ShowWindow(HWND(hwnd as *mut c_void), SW_RESTORE); }
}

#[cfg(not(windows))]
pub fn restore(_hwnd: isize) {}

#[cfg(windows)]
pub fn is_iconic(hwnd: isize) -> bool {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::IsIconic;
    unsafe { IsIconic(HWND(hwnd as *mut c_void)).as_bool() }
}

#[cfg(not(windows))]
pub fn is_iconic(_hwnd: isize) -> bool { false }







#[cfg(windows)]
pub fn click(hwnd: isize, x: i32, y: i32) -> bool {
    use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{PostMessageW, WM_LBUTTONDOWN, WM_LBUTTONUP};
    let lp = (((y & 0xFFFF) << 16) | (x & 0xFFFF)) as isize;
    unsafe {
        PostMessageW(HWND(hwnd as *mut c_void), WM_LBUTTONDOWN, WPARAM(1), LPARAM(lp)).is_ok()
            && { std::thread::sleep(std::time::Duration::from_millis(80)); true }
            && PostMessageW(HWND(hwnd as *mut c_void), WM_LBUTTONUP, WPARAM(0), LPARAM(lp)).is_ok()
    }
}

#[cfg(not(windows))]
pub fn click(_hwnd: isize, _x: i32, _y: i32) -> bool { false }

#[cfg(windows)]
fn frame_rect(hwnd: isize) -> Option<windows::Win32::Foundation::RECT> {
    use windows::Win32::Foundation::{HWND, RECT};
    use windows::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_EXTENDED_FRAME_BOUNDS};
    let mut r = RECT::default();
    let ok = unsafe { DwmGetWindowAttribute(HWND(hwnd as *mut c_void), DWMWA_EXTENDED_FRAME_BOUNDS, &mut r as *mut _ as *mut _, std::mem::size_of::<RECT>() as u32) };
    if ok.is_err() || r.right <= r.left || r.bottom <= r.top { None } else { Some(r) }
}

#[cfg(windows)]
pub fn window_size(hwnd: isize) -> (u32, u32) {
    match frame_rect(hwnd) {
        Some(r) => ((r.right - r.left) as u32, (r.bottom - r.top) as u32),
        None => (0, 0),
    }
}

#[cfg(not(windows))]
pub fn window_size(_hwnd: isize) -> (u32, u32) { (0, 0) }

#[cfg(windows)]
pub fn client_offset(hwnd: isize) -> Option<(i32, i32)> {
    use windows::Win32::Foundation::{HWND, POINT};
    use windows::Win32::Graphics::Gdi::ClientToScreen;
    let fr = frame_rect(hwnd)?;
    let mut pt = POINT { x: 0, y: 0 };
    unsafe { if ClientToScreen(HWND(hwnd as *mut c_void), &mut pt).0 == 0 { return None; } }
    Some((pt.x - fr.left, pt.y - fr.top))
}

#[cfg(not(windows))]
pub fn client_offset(_hwnd: isize) -> Option<(i32, i32)> { None }

#[cfg(windows)]
pub fn client_size(hwnd: isize) -> (u32, u32) {
    use windows::Win32::Foundation::{HWND, RECT};
    use windows::Win32::UI::WindowsAndMessaging::GetClientRect;
    let mut r = RECT::default();
    unsafe { let _ = GetClientRect(HWND(hwnd as *mut c_void), &mut r); }
    ((r.right - r.left) as u32, (r.bottom - r.top) as u32)
}

#[cfg(not(windows))]
pub fn client_size(_hwnd: isize) -> (u32, u32) { (0, 0) }

#[cfg(windows)]
pub fn dpi_of(hwnd: isize) -> u32 {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::HiDpi::GetDpiForWindow;
    unsafe { GetDpiForWindow(HWND(hwnd as *mut c_void)) }
}

#[cfg(not(windows))]
pub fn dpi_of(_hwnd: isize) -> u32 { 96 }


pub fn log(msg: &str) {
    #[cfg(windows)]
    {
        use std::io::Write;
        if let Ok(dir) = std::env::var("LOCALAPPDATA") {
            let path = std::path::Path::new(&dir).join("DoudianRemoteQR");
            let _ = std::fs::create_dir_all(&path);
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path.join("agent.log")) {
                let _ = writeln!(f, "{} {}", chrono_now(), msg);
            }
        }
    }
    #[cfg(not(windows))]
    eprintln!("{msg}");
}

fn chrono_now() -> String {
    let secs = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    format!("{secs}")
}

#[cfg(windows)]
pub fn single_instance(name: &str) -> bool {
    use windows::core::HSTRING;
    use windows::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS};
    use windows::Win32::System::Threading::CreateMutexW;
    let user = std::env::var("USERNAME").unwrap_or_else(|_| "user".into());
    let name = HSTRING::from(format!("Local\\{name}.{user}"));
    unsafe {
        let h = CreateMutexW(None, true, &name);
        if h.is_err() { return false; }
        GetLastError() != ERROR_ALREADY_EXISTS
    }
}

#[cfg(not(windows))]
pub fn single_instance(_name: &str) -> bool { true }
