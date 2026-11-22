from __future__ import annotations
import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_CANCELMODE = 0x001F

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

def is_window(hwnd): return bool(user32.IsWindow(hwnd))
def is_iconic(hwnd): return bool(user32.IsIconic(hwnd))
def get_pid(hwnd):
    pid = wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)); return pid.value

def get_client_rect(hwnd):
    r = RECT(); user32.GetClientRect(hwnd, ctypes.byref(r)); return r

def screen_to_client(hwnd, x, y):
    pt = wintypes.POINT(int(x), int(y)); user32.ScreenToClient(hwnd, ctypes.byref(pt)); return pt.x, pt.y

def dwm_extended_frame_bounds(hwnd):
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9
    class RECT2(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
    r = RECT2()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r))
    return r

def post_message(hwnd, msg, wparam, lparam):
    try:
        import win32gui
        win32gui.PostMessage(hwnd, msg, wparam, lparam)
        return True
    except Exception:
        return False

def click_at(hwnd, x, y):
    """x,y are client coordinates; click with PostMessage. Returns (down_ok, up_ok)."""
    lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    down = post_message(hwnd, WM_LBUTTONDOWN, 1, lparam)
    time.sleep(0.08)
    up = post_message(hwnd, WM_LBUTTONUP, 0, lparam) if is_window(hwnd) else False
    if not up:
        post_message(hwnd, WM_CANCELMODE, 0, 0)
    return down, up
