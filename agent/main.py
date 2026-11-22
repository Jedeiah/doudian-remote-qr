from __future__ import annotations
import argparse, asyncio, base64, ctypes, os, time
from pathlib import Path
import httpx
import numpy as np

if os.name == "nt":
    import win32gui

from .detect import crop_roi, find_solid_blue_rect, detect_qr, qr_digest, crop_with_quiet_zone, valid_jpeg
from .click import is_window, is_iconic, get_pid, get_client_rect, screen_to_client, dwm_extended_frame_bounds, click_at
from .ws_client import AgentWS

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def login(server, username, password, seat_name, fingerprint):
    r = httpx.post(server.rstrip("/") + "/auth/login", json={
        "username": username, "password": password, "role": "seat", "seat_name": seat_name,
        "device_fingerprint": fingerprint}, timeout=10)
    r.raise_for_status()
    data = r.json()
    cookie = r.headers.get("set-cookie", "").split(";", 1)[0]
    return data, cookie

def find_doudian_window():
    found = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            found.append((hwnd, title, cls, get_pid(hwnd)))
        return True
    win32gui.EnumWindows(cb, None)
    for hwnd, title, cls, pid in found:
        if "抖店" in title or "登录" in title or "doudian" in cls.lower():
            return hwnd, title, pid
    return None, None, None

def get_dpi(hwnd):
    try:
        return ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    except Exception:
        return 96

def encode_jpg(jpg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpg).decode()

async def run(args):
    if os.name != "nt":
        raise SystemExit("Agent only runs on Windows")
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception: pass
    if not getattr(args, "no_single", False):
        from .single_instance import acquire
        if not acquire():
            log("已有实例在运行，退出"); return
    fingerprint = os.getenv("COMPUTERNAME", "pc") + ":win"
    if os.getenv("DRQ_COOKIE"):
        cookie = os.environ["DRQ_COOKIE"]
        me = httpx.get(args.server.rstrip("/") + "/auth/me", headers={"Cookie": cookie}, timeout=10).json()
        seat_id = me["seat_id"]; args.seat_name = me.get("seat_name") or args.seat_name
        log("使用面板登录态 seat_id=", seat_id)
    else:
        data, cookie = login(args.server, args.username, args.password, args.seat_name, fingerprint)
        seat_id = data["seat_id"]
        log("登录成功 seat_id=", seat_id)
    hwnd = args.hwnd
    title = None
    if not hwnd:
        hwnd, title, _ = find_doudian_window()
    if not hwnd:
        raise SystemExit("未找到抖店窗口，请用 --hwnd 指定")
    pid = get_pid(hwnd)
    window_key = f"{pid}:{hwnd}"
    r = httpx.post(args.server.rstrip("/") + "/sessions",
                   json={"shop_name": args.shop, "window_key": window_key, "hwnd": hwnd, "pid": pid},
                   headers={"Cookie": cookie}, timeout=10)
    if r.status_code != 200:
        raise SystemExit("创建会话失败: " + r.text)
    sess = r.json(); sid = sess["session_id"]; current_attempt = sess["attempt_id"]
    log("会话创建", sid)

    latest = {"buf": None, "ts": 0}
    loop = asyncio.get_running_loop()
    from windows_capture import WindowsCapture
    cap = WindowsCapture(window_hwnd=hwnd, cursor_capture=False, draw_border=False)
    @cap.event
    def on_frame_arrived(frame, control):
        buf = frame.frame_buffer
        latest["buf"] = buf[:, :, :3].copy() if buf.ndim == 3 and buf.shape[2] == 4 else buf.copy()
        latest["ts"] = getattr(frame, "timespan", 0)
    @cap.event
    def on_closed():
        log("WGC closed"); latest["closed"] = True
    if hasattr(cap, "start_free_threaded"):
        cap.start_free_threaded()
    else:
        import threading
        threading.Thread(target=cap.start, daemon=True).start()

    ws = AgentWS(args.server.replace("https://", "wss://").replace("http://", "ws://") + "/ws/agent", cookie, seat_id)
    q2 = asyncio.Queue()
    await ws.connect(q2)
    btn_present = [False]

    async def on_cmd(msg):
        nonlocal current_attempt
        t = msg.get("type")
        log("收到命令", t)
        if t == "force.logout":
            log("被强制下线"); os._exit(0)
        if t in ("cmd.refresh", "cmd.arm"):
            current_attempt = msg.get("attempt_id") or current_attempt
            if t == "cmd.arm":
                return
            await asyncio.sleep(0.4)  # let latest frame refresh
            buf = latest["buf"]
            if buf is None:
                await ws.send({"type": "click.rejected", "session_id": sid, "request_id": msg.get("request_id"),
                               "attempt_id": msg.get("attempt_id"), "reason": "no_frame"}); return
            roi, offset = crop_roi(buf)
            btn = find_solid_blue_rect(roi)
            if btn is None:
                log("刷新按钮未找到")
                await ws.send({"type": "click.rejected", "session_id": sid, "request_id": msg.get("request_id"),
                               "attempt_id": msg.get("attempt_id"), "reason": "btn_not_found"}); return
            fr = dwm_extended_frame_bounds(hwnd)
            sx = fr.left + btn.cx + offset[0]; sy = fr.top + btn.cy + offset[1]
            cx, cy = screen_to_client(hwnd, sx, sy)
            cr = get_client_rect(hwnd)
            if not (0 <= cx < cr.right and 0 <= cy < cr.bottom):
                await ws.send({"type": "click.rejected", "session_id": sid, "request_id": msg.get("request_id"),
                               "attempt_id": msg.get("attempt_id"), "reason": "out_of_client"}); return
            down, up = click_at(hwnd, cx, cy)
            log("click", cx, cy, down, up)
            if down and up:
                await ws.send({"type": "click.sent", "session_id": sid, "request_id": msg.get("request_id"),
                               "attempt_id": msg.get("attempt_id")})
            else:
                await ws.send({"type": "click.rejected", "session_id": sid, "request_id": msg.get("request_id"),
                               "attempt_id": msg.get("attempt_id"), "reason": "post_failed"})
        elif t == "cmd.rearm":
            btn_present[0] = False

    ws.on_command = on_cmd
    asyncio.create_task(ws.recv_loop())
    phase = ["WAIT_QR"]; done = asyncio.Event()
    async def state_loop():
        while True:
            msg = await q2.get()
            if msg.get("type") == "state" and msg.get("session_id") == sid:
                phase[0] = msg.get("state", phase[0])
                if phase[0] in ("DONE", "CLOSED"):
                    done.set()
    asyncio.create_task(state_loop())
    log("开始采集")
    last_sent = None
    last_sent_at = 0
    while not done.is_set():
        await asyncio.sleep(0.2)
        if latest.get("closed"):
            await ws.send({"type": "window.unavailable", "session_id": sid, "reason": "closed"})
            break
        buf = latest["buf"]
        if buf is None:
            continue
        h, w = buf.shape[:2]
        roi, offset = crop_roi(buf)
        btn = find_solid_blue_rect(roi)
        if btn:
            if not btn_present[0]:
                btn_present[0] = True
                await ws.send({"type": "btn.detected", "session_id": sid, "request_id": "btn-" + str(time.time_ns()),
                               "btn_rel": [(btn.cx + offset[0]) / w, (btn.cy + offset[1]) / h],
                               "frame_w": w, "frame_h": h, "dpi": get_dpi(hwnd)})
                log("上报 btn.detected")
            continue
        btn_present[0] = False
        data_, pts, _ = detect_qr(roi)
        if pts is None:
            continue
        pts_full = pts + np.array(offset)
        cropped = crop_with_quiet_zone(buf, pts_full)
        if not cropped:
            continue
        jpg, _, _, _ = cropped
        if not valid_jpeg(jpg):
            continue
        if phase[0] in ("VALID", "SCANNED", "DONE", "CLOSED", "PENDING_REPLACE"):
            continue
        digest = qr_digest(data_, pts, roi)
        now = time.time()
        if digest == last_sent and now - last_sent_at < 55:
            continue
        last_sent = digest; last_sent_at = now
        await ws.send({"type": "qr.detected", "session_id": sid, "request_id": "qr-" + str(time.time_ns()),
                       "jpg": encode_jpg(jpg), "digest": digest, "attempt_id": current_attempt,
                       "captured_at": latest["ts"]})
        log("上报 qr.detected")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True)
    ap.add_argument("--username", default="seat")
    ap.add_argument("--password", required=True)
    ap.add_argument("--seat-name", required=True)
    ap.add_argument("--shop", required=True)
    ap.add_argument("--hwnd", type=int)
    ap.add_argument("--no-single", action="store_true")
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
