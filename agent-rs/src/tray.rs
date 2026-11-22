#![cfg(windows)]
use windows::core::PCWSTR;
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, WPARAM};
use windows::Win32::UI::Shell::{Shell_NotifyIconW, NIF_ICON, NIF_MESSAGE, NIF_TIP, NIM_ADD, NIM_DELETE, NOTIFYICONDATAW};
use windows::Win32::UI::WindowsAndMessaging::*;
use windows::Win32::System::LibraryLoader::GetModuleHandleW;

const WM_TRAY: u32 = WM_APP + 1;
const ID_OPEN: usize = 1001;
const ID_QUIT: usize = 1002;

fn wide(s: &str) -> Vec<u16> { s.encode_utf16().chain(std::iter::once(0)).collect() }

unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, w: WPARAM, l: LPARAM) -> LRESULT {
    match msg {
        WM_TRAY => {
            match l.0 as u32 {
                WM_LBUTTONDBLCLK => { open::that("http://127.0.0.1:8765/").ok(); }
                WM_RBUTTONUP => {
                    let menu = CreatePopupMenu().unwrap_or_default();
                    let _ = AppendMenuW(menu, MF_STRING, ID_OPEN, PCWSTR(wide("打开面板").as_ptr()));
                    let _ = AppendMenuW(menu, MF_STRING, ID_QUIT, PCWSTR(wide("退出").as_ptr()));
                    let mut pt = windows::Win32::Foundation::POINT::default();
                    let _ = GetCursorPos(&mut pt);
                    let _ = SetForegroundWindow(hwnd);
                    let cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None);
                    let _ = DestroyMenu(menu);
                    let _ = PostMessageW(hwnd, WM_NULL, WPARAM(0), LPARAM(0));
                    if cmd.0 as usize == ID_OPEN { open::that("http://127.0.0.1:8765/").ok(); }
                    else if cmd.0 as usize == ID_QUIT { DestroyWindow(hwnd).ok(); }
                }
                _ => {}
            }
            LRESULT(0)
        }
        WM_DESTROY => { PostQuitMessage(0); LRESULT(0) }
        _ => DefWindowProcW(hwnd, msg, w, l),
    }
}

pub fn run_tray() {
    unsafe {
        let hinst = GetModuleHandleW(PCWSTR::null()).unwrap();
        let class = wide("DRQTrayWnd");
        let wc = WNDCLASSW {
            style: CS_DBLCLKS,
            lpfnWndProc: Some(wndproc),
            hInstance: hinst.into(),
            lpszClassName: PCWSTR(class.as_ptr()),
            ..Default::default()
        };
        RegisterClassW(&wc);
        let hwnd = CreateWindowExW(WINDOW_EX_STYLE(0), PCWSTR(class.as_ptr()), PCWSTR(wide("抖店扫码助手").as_ptr()),
            WS_OVERLAPPED, 0, 0, 0, 0, None, None, hinst, None).unwrap();
        let mut nid = NOTIFYICONDATAW::default();
        nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = hwnd;
        nid.uID = 1;
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        nid.uCallbackMessage = WM_TRAY;
        let hi: windows::Win32::Foundation::HINSTANCE = hinst.into();
        let hicon = LoadIconW(hi, PCWSTR(1 as *const u16)).ok();
        nid.hIcon = hicon.unwrap_or_else(|| LoadIconW(None, IDI_APPLICATION).unwrap_or_default());
        let tip = wide("抖店扫码助手 · 在线");
        let n = tip.len().min(nid.szTip.len());
        nid.szTip[..n].copy_from_slice(&tip[..n]);
        let _ = Shell_NotifyIconW(NIM_ADD, &nid);
        let mut msg = MSG::default();
        while GetMessageW(&mut msg, None, 0, 0).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        let _ = Shell_NotifyIconW(NIM_DELETE, &nid);
    }
}
