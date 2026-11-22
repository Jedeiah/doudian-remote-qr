from __future__ import annotations
import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import COOKIE_NAME, SESSION_TTL_HOURS, BUSINESS_TTL_MINUTES, WAIT_QR_SECONDS, BASE_DIR
from . import accounts, auth, state, hub
from .db import init_schema
from .models import BizSession

ROOT = BASE_DIR
SCAN_DIR = ROOT / "scan-web"
ADMIN_DIR = ROOT / "admin-web"
SCAN_DIR.mkdir(exist_ok=True)
ADMIN_DIR.mkdir(exist_ok=True)

# ---------- helpers ----------
_tasks: dict[tuple[str, str], asyncio.Task] = {}
_login_fail: dict[str, list] = {}

def _login_allowed(key: str) -> bool:
    now = time.time()
    arr = [t for t in _login_fail.get(key, []) if now - t < 600]
    _login_fail[key] = arr
    return len(arr) < 5

def _login_failed(key: str):
    _login_fail.setdefault(key, []).append(time.time())

def _password_ok(p: str) -> bool:
    return len(p) >= 10 and any(c.isalpha() for c in p) and any(c.isdigit() for c in p)

def _touch_ttl(s: BizSession):
    _schedule(s.id, "ttl", BUSINESS_TTL_MINUTES * 60, ttl_timeout, s.id)

def _cancel_task(sid: str, kind: str):
    t = _tasks.pop((sid, kind), None)
    if t and not t.done() and t is not asyncio.current_task():
        t.cancel()

def _schedule(sid: str, kind: str, delay: float, fn, *args):
    _cancel_task(sid, kind)
    async def runner():
        try:
            await asyncio.sleep(delay)
            await fn(*args)
        except asyncio.CancelledError:
            pass
    _tasks[(sid, kind)] = asyncio.create_task(runner())

def _broadcast_pending():
    return {"type": "sessions", "items": state.pending_list()}

async def broadcast_pending():
    await hub.send_to_scan(_broadcast_pending())

async def broadcast_state(s: BizSession):
    payload = {"type": "state", "session_id": s.id, "state": s.state, "count": s.refresh_count}
    await hub.send_to_subscribers(s, payload)
    await hub.send_to_agent(s.seat_id, payload)

async def close_session(s: BizSession, reason: str):
    if s.is_terminal:
        return
    s.state = "CLOSED"; s.closed_reason = reason; s.qr_jpeg = None
    _cancel_task(s.id, "ttl"); _cancel_task(s.id, "wait_qr"); _cancel_task(s.id, "refresh")
    await broadcast_state(s); await broadcast_pending()
    for ws in list(s.subscribers):
        await hub.safe_send(ws, {"type": "closed", "session_id": s.id, "reason": reason})
    state.remove(s.id)

async def finish_session(s: BizSession):
    if s.is_terminal:
        return
    s.state = "DONE"; s.qr_jpeg = None
    _cancel_task(s.id, "ttl"); _cancel_task(s.id, "wait_qr"); _cancel_task(s.id, "refresh")
    await broadcast_state(s); await broadcast_pending()
    for ws in list(s.subscribers):
        await hub.safe_send(ws, {"type": "done", "session_id": s.id})
    state.remove(s.id)

async def wait_qr_timeout(sid: str):
    s = state.get(sid)
    if s and s.state == "WAIT_QR":
        await close_session(s, "no_qr")

async def ttl_timeout(sid: str):
    s = state.get(sid)
    if s and not s.is_terminal:
        await close_session(s, "ttl")

async def refresh_timeout(sid: str, attempt_id: str):
    s = state.get(sid)
    if not s or s.state != "REFRESHING" or s.attempt_id != attempt_id:
        return
    if s.manual_done:
        await _need_manual(s)
        return
    if s.retry_failed == 0:
        # retry once per refresh attempt
        s.attempt_id = state.new_id(); s.click_acked = False; s.refresh_count += 1; s.retry_failed = 1
        await hub.send_to_agent(s.seat_id, {"type": "cmd.refresh", "session_id": s.id, "request_id": state.new_id(),
                                            "attempt_id": s.attempt_id, "btn_full": s.last_btn_full, "btn_geom": s.btn_geom})
        await broadcast_state(s)
        _schedule(s.id, "refresh", 15, refresh_timeout, s.id, s.attempt_id)
    else:
        await _need_manual(s)

async def _need_manual(s: BizSession):
    # 自动刷新失败：直接结束业务会话，避免进入没有出口的“需人工”死状态
    await close_session(s, "auto_refresh_failed")

async def _start_refresh(s: BizSession):
    s.state = "REFRESHING"; s.qr_jpeg = None
    s.attempt_id = state.new_id(); s.click_acked = False; s.manual_done = False; s.retry_failed = 0
    s.refresh_count += 1
    _touch_ttl(s)
    await broadcast_state(s); await broadcast_pending()
    if not await hub.send_to_agent(s.seat_id, {"type": "cmd.refresh", "session_id": s.id, "request_id": state.new_id(),
                                         "attempt_id": s.attempt_id, "btn_full": s.last_btn_full, "btn_geom": s.btn_geom}):
        await close_session(s, "agent_offline")
        return
    _schedule(s.id, "refresh", 15, refresh_timeout, s.id, s.attempt_id)

# ---------- lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_schema()
    for _u, _r in (("admin", "admin"), ("seat", "seat"), ("scanner", "scanner")):
        if not accounts.get_account(_u):
            _pwd = os.getenv(_u.upper() + "_PASSWORD") or secrets.token_urlsafe(12)
            accounts.create_account(_u, _pwd, _r, must_change=(_r == "admin"))
            print("=" * 56)
            print(f"首次启动：{_u} 初始密码 = {_pwd}")
            print("=" * 56)
    yield

app = FastAPI(title="Doudian Remote QR Login", lifespan=lifespan)

# ---------- static ----------
@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/")
async def root():
    return FileResponse(SCAN_DIR / "login.html")

@app.get("/scan")
@app.get("/scan/")
async def scan_page():
    return FileResponse(SCAN_DIR / "login.html")

@app.get("/scan/app")
async def scan_app():
    s = auth.get_login  # placeholder
    return FileResponse(SCAN_DIR / "index.html")

@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    return FileResponse(ADMIN_DIR / "login.html")

@app.get("/admin/app")
async def admin_app():
    return FileResponse(ADMIN_DIR / "index.html")

app.mount("/scan/static", StaticFiles(directory=SCAN_DIR), name="scan-static")
app.mount("/admin/static", StaticFiles(directory=ADMIN_DIR), name="admin-static")

# ---------- request models ----------
class LoginBody(BaseModel):
    username: str
    password: str
    role: Optional[str] = None
    seat_name: Optional[str] = None
    device_fingerprint: Optional[str] = None

class PasswordBody(BaseModel):
    new_password: str = Field(min_length=10)

class CreateSessionBody(BaseModel):
    shop_name: str
    window_key: str
    hwnd: int
    pid: int
    operation_id: Optional[str] = None

class PasswordChangeBody(BaseModel):
    old_password: str
    new_password: str

# ---------- auth ----------
def _set_cookie(response: Response, sid: str, request: Request):
    secure = request.url.scheme == "https" or os.getenv("COOKIE_SECURE", "") == "1"
    response.set_cookie(COOKIE_NAME, sid, max_age=SESSION_TTL_HOURS * 3600,
                        httponly=True, secure=secure, samesite="strict", path="/")

@app.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    key = (request.client.host if request.client else "?") + ":" + body.username
    if not _login_allowed(key):
        raise HTTPException(429, "尝试过多，请 10 分钟后再试")
    acc = accounts.get_account(body.username)
    if not acc or not accounts.verify_password(acc["password_hash"], body.password):
        _login_failed(key)
        raise HTTPException(401, "账号或密码错误")
    if body.role and body.role != acc["role"]:
        raise HTTPException(403, "角色不匹配")
    seat_id = None
    if acc["role"] == "seat":
        if not body.seat_name:
            raise HTTPException(400, "seat_name required")
        if not (body.device_fingerprint or "").strip():
            raise HTTPException(400, "device_fingerprint required")
        try:
            seat_id = accounts.ensure_seat(acc["id"], body.seat_name.strip(), body.device_fingerprint.strip())
        except ValueError:
            raise HTTPException(409, "该坐席名称已被其他设备占用")
    _login_fail.pop(key, None)
    s = auth.create_login(acc["username"], acc["role"], seat_id, body.seat_name, bool(acc["must_change_password"]))
    _set_cookie(response, s.sid, request)
    return {"ok": True, "role": acc["role"], "seat_id": seat_id, "must_change_password": bool(acc["must_change_password"])}

@app.get("/auth/me")
async def me(request: Request):
    s = auth.get_login(request.cookies.get(COOKIE_NAME))
    if not s:
        raise HTTPException(401, "not_logged_in")
    return {"username": s.username, "role": s.role, "seat_id": s.seat_id, "seat_name": s.seat_name, "must_change_password": s.must_change_password}

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    s = auth.get_login(request.cookies.get(COOKIE_NAME))
    if s:
        auth.delete_login(s.sid)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}

@app.post("/auth/change-password")
async def change_password(body: PasswordChangeBody, request: Request):
    s = auth.current_login(request)
    if s.role != "admin":
        raise HTTPException(403, "仅管理员可修改密码")
    acc = accounts.get_account(s.username)
    if not acc or not accounts.verify_password(acc["password_hash"], body.old_password):
        raise HTTPException(400, "原密码错误")
    if not _password_ok(body.new_password):
        raise HTTPException(400, "密码至少10位且需包含字母和数字")
    if body.old_password == body.new_password:
        raise HTTPException(400, "新密码不能与原密码相同")
    accounts.set_password(s.username, body.new_password, must_change=False)
    sids = auth.revoke_user(s.username)
    await hub.close_sids(sids)
    return {"ok": True}

# ---------- admin ----------
def admin_dep(request: Request):
    s = auth.get_login(request.cookies.get(COOKIE_NAME))
    if not s or s.role != "admin":
        raise HTTPException(401, "admin_only")
    if s.must_change_password:
        raise HTTPException(403, "must_change_password")
    return s

@app.get("/admin/accounts")
async def admin_accounts(_: auth.LoginSession = Depends(admin_dep)):
    return {"items": accounts.list_accounts()}

@app.put("/admin/accounts/{username}/password")
async def admin_set_password(username: str, body: PasswordBody, _: auth.LoginSession = Depends(admin_dep)):
    if not _password_ok(body.new_password):
        raise HTTPException(400, "密码至少10位且需包含字母和数字")
    if not accounts.set_password(username, body.new_password, must_change=False):
        raise HTTPException(404, "account_not_found")
    sids = auth.revoke_user(username)
    await hub.close_sids(sids)
    acc = accounts.get_account(username)
    if acc and acc["role"] == "seat":
        for row in accounts.list_seats():
            if row["account_id"] == acc["id"]:
                for s in list(state.active_for_seat(row["seat_id"])):
                    await close_session(s, "force_logout")
    return {"ok": True}

@app.get("/admin/seats")
async def admin_seats(_: auth.LoginSession = Depends(admin_dep)):
    items = []
    for row in accounts.list_seats():
        active = [s for s in state.active_for_seat(row["seat_id"])]
        items.append({**row, "online": row["seat_id"] in hub.agent_sockets,
                      "current_session_id": active[0].id if active else None})
    return {"items": items}

@app.post("/admin/seats/{seat_id}/force-logout")
async def admin_force_logout(seat_id: str, _: auth.LoginSession = Depends(admin_dep)):
    sids = auth.revoke_seat(seat_id)
    await hub.close_sids(sids)
    for s in list(state.all_sessions()):
        if s.seat_id == seat_id and not s.is_terminal:
            await close_session(s, "force_logout")
    await hub.send_to_agent(seat_id, {"type": "force.logout", "seat_id": seat_id, "reason": "admin"})
    return {"ok": True}

@app.get("/admin/sessions")
async def admin_sessions(_: auth.LoginSession = Depends(admin_dep)):
    return {"items": [{"session_id": s.id, "shop_name": s.shop_name, "seat_name": s.seat_name, "state": s.state}
                      for s in state.all_sessions() if not s.is_terminal]}

@app.delete("/admin/seats/{seat_id}")
async def admin_delete_seat(seat_id: str, _: auth.LoginSession = Depends(admin_dep)):
    sids = auth.revoke_seat(seat_id)
    await hub.close_sids(sids)
    for s in list(state.all_sessions()):
        if s.seat_id == seat_id and not s.is_terminal:
            await close_session(s, "seat_deleted")
    accounts.delete_seat(seat_id)
    return {"ok": True}

# ---------- business session ----------
def seat_dep(request: Request):
    s = auth.get_login(request.cookies.get(COOKIE_NAME))
    if not s or s.role != "seat":
        raise HTTPException(401, "seat_only")
    if s.must_change_password:
        raise HTTPException(403, "must_change_password")
    return s

@app.post("/sessions")
async def create_session(body: CreateSessionBody, request: Request):
    login = seat_dep(request)
    if not body.shop_name.strip():
        raise HTTPException(400, "店铺名不能为空")
    if not login.seat_id:
        raise HTTPException(400, "seat_not_bound")
    if body.operation_id:
        for s in state.all_sessions():
            if s.seat_id == login.seat_id and s.operation_id == body.operation_id and not s.is_terminal:
                return {"ok": True, "session_id": s.id, "attempt_id": s.attempt_id}
    active = state.active_for_seat(login.seat_id)
    if active:
        raise HTTPException(409, {"message": "本坐席已有进行中的会话，请先完成或取消后再发起下一单", "session_id": active[0].id})
    for s in state.all_sessions():
        if s.shop_key == state.shop_key(body.shop_name) and not s.is_terminal:
            raise HTTPException(409, "该店铺已有进行中的会话")
    s = state.create(body.shop_name.strip(), login.seat_id, login.seat_name or "", body.window_key, body.hwnd, body.pid, body.operation_id)
    _schedule(s.id, "ttl", BUSINESS_TTL_MINUTES * 60, ttl_timeout, s.id)
    _schedule(s.id, "wait_qr", WAIT_QR_SECONDS, wait_qr_timeout, s.id)
    await broadcast_pending()
    return {"ok": True, "session_id": s.id, "attempt_id": s.attempt_id}

@app.get("/scan/sessions")
async def scan_sessions(request: Request):
    login = auth.get_login(request.cookies.get(COOKIE_NAME))
    if not login or login.role != "scanner":
        raise HTTPException(401, "scanner_only")
    if login.must_change_password:
        raise HTTPException(403, "must_change_password")
    return {"items": state.pending_list()}

async def _scan_action(sid: str, request: Request, action: str):
    login = auth.get_login(request.cookies.get(COOKIE_NAME))
    if not login or login.role != "scanner":
        raise HTTPException(401, "scanner_only")
    if login.must_change_password:
        raise HTTPException(403, "must_change_password")
    s = state.get(sid)
    if not s:
        raise HTTPException(404, "session_not_found")
    if action == "scanned":
        if s.state == "SCANNED":
            return {"ok": True, "state": "SCANNED"}
        if s.state not in ("VALID", "REFRESHING"):
            raise HTTPException(409, "state_not_scannable")
        s.state = "SCANNED"; s.qr_jpeg = None
        _touch_ttl(s)
        await broadcast_state(s); await broadcast_pending()
    else:
        if s.is_terminal:
            raise HTTPException(409, "already_closed")
        await close_session(s, "reject")
    return {"ok": True}

@app.post("/scan/sessions/{sid}/scanned")
async def scan_mark_scanned(sid: str, request: Request):
    return await _scan_action(sid, request, "scanned")

@app.post("/scan/sessions/{sid}/reject")
async def scan_mark_rejected(sid: str, request: Request):
    return await _scan_action(sid, request, "reject")

@app.get("/scan/sessions/{sid}")
async def scan_session(sid: str, request: Request):
    login = auth.get_login(request.cookies.get(COOKIE_NAME))
    if not login or login.role != "scanner":
        raise HTTPException(401, "scanner_only")
    if login.must_change_password:
        raise HTTPException(403, "must_change_password")
    s = state.get(sid)
    if not s:
        raise HTTPException(404, "session_not_found")
    return {"session_id": s.id, "shop_name": s.shop_name, "seat_name": s.seat_name,
            "state": s.state, "count": s.refresh_count,
            "qr_jpeg": s.qr_jpeg if s.state == "VALID" else None}

@app.get("/sessions/current")
async def current_session(request: Request):
    login = seat_dep(request)
    active = state.active_for_seat(login.seat_id)
    return {"sessions": [{"session_id": x.id, "shop_name": x.shop_name, "state": x.state,
                          "count": x.refresh_count,
                          "qr_jpeg": x.qr_jpeg if x.state == "VALID" else None} for x in active]}

@app.get("/sessions/{sid}")
async def get_session(sid: str, request: Request):
    login = seat_dep(request)
    s = state.get(sid)
    if not s or s.seat_id != login.seat_id:
        raise HTTPException(404, "not_found")
    return {"session_id": s.id, "shop_name": s.shop_name, "state": s.state, "count": s.refresh_count,
            "qr_jpeg": s.qr_jpeg, "attempt_id": s.attempt_id}

@app.post("/sessions/{sid}/confirm")
async def confirm_session(sid: str, request: Request):
    login = seat_dep(request)
    s = state.get(sid)
    if not s:
        return {"ok": True, "already_ended": True}
    if s.seat_id != login.seat_id:
        raise HTTPException(404, "not_found")
    if s.state not in ("VALID", "SCANNED"):
        raise HTTPException(409, "state_not_confirmable")
    await finish_session(s)
    return {"ok": True}

@app.post("/sessions/{sid}/cancel")
async def cancel_session(sid: str, request: Request):
    login = seat_dep(request)
    s = state.get(sid)
    if not s:
        return {"ok": True, "already_ended": True}
    if s.seat_id != login.seat_id:
        raise HTTPException(404, "not_found")
    await close_session(s, "seat_cancel")
    return {"ok": True}

# ---------- agent WebSocket ----------
@app.websocket("/ws/agent")
async def agent_ws(ws: WebSocket):
    login = auth.get_login(ws.cookies.get(COOKIE_NAME))
    if not login or login.role != "seat" or not login.seat_id:
        await ws.close(code=4401)
        return
    await ws.accept()
    seat_id = login.seat_id
    sid = ws.cookies.get(COOKIE_NAME)
    ws.scope["drq_sid"] = sid
    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if hello.get("type") != "agent.hello":
            await ws.close(code=4401); return
        old = hub.agent_sockets.get(seat_id)
        if old is not None and old is not ws:
            try: await old.close(code=4409)
            except Exception: pass
        hub.agent_sockets[seat_id] = ws
        active = [s for s in state.active_for_seat(seat_id)]
        await ws.send_json({"type": "agent.snapshot", "seat_id": seat_id, "seat_name": login.seat_name,
                            "sessions": [{"session_id": s.id, "window_key": s.window_key, "state": s.state,
                                          "attempt_id": s.attempt_id} for s in active]})
        while True:
            msg = await ws.receive_json()
            fresh = auth.get_login(sid)
            if not fresh or fresh.role != "seat" or fresh.seat_id != seat_id:
                await ws.close(code=4401); return
            await handle_agent_message(ws, fresh, msg)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        if hub.agent_sockets.get(seat_id) is ws:
            hub.agent_sockets.pop(seat_id, None)
            for s in list(state.active_for_seat(seat_id)):
                await close_session(s, "agent_offline")

async def handle_agent_message(ws: WebSocket, login: auth.LoginSession, msg: dict):
    typ = msg.get("type")
    sid = msg.get("session_id", "")
    s = state.get(sid)
    if not s or s.seat_id != login.seat_id:
        return
    rid = msg.get("request_id")
    if typ == "btn.detected":
        s.last_btn_full = msg.get("btn_rel")
        s.btn_geom = [msg.get("frame_w", 0), msg.get("frame_h", 0), msg.get("dpi", 0)]
        s.last_btn_at = time.time()
        if s.state in ("WAIT_QR", "VALID"):
            await _start_refresh(s)
    elif typ == "qr.detected":
        if s.state == "REFRESHING" and not (s.click_acked or s.manual_done):
            s.pending_qr = msg
            return
        if s.state == "WAIT_QR" or (s.state == "REFRESHING" and msg.get("attempt_id") == s.attempt_id
                                    and (s.click_acked or s.manual_done)):
            if s.state == "REFRESHING" and s.old_digest and msg.get("digest") == s.old_digest:
                return   # 同一二维码，刷新未产生新码

            jpg = msg.get("jpg") or ""
            if not jpg.startswith("data:image/jpeg;base64,") or len(jpg) > 200_000:
                return
            s.qr_jpeg = jpg
            s.old_digest = msg.get("digest")
            s.state = "VALID"
            s.manual_done = False
            _touch_ttl(s)
            _cancel_task(s.id, "wait_qr"); _cancel_task(s.id, "refresh")
            await broadcast_state(s); await broadcast_pending()
            await hub.send_to_subscribers(s, {"type": "frame", "session_id": s.id, "data": jpg, "state": "VALID"})
    elif typ == "click.sent":
        if s.state == "REFRESHING" and msg.get("attempt_id") == s.attempt_id and not s.click_acked:
            s.click_acked = True
            _schedule(s.id, "refresh", 15, refresh_timeout, s.id, s.attempt_id)
            if s.pending_qr:
                pending = s.pending_qr; s.pending_qr = None
                await handle_agent_message(ws, login, pending)
    elif typ == "click.rejected":
        if s.state == "REFRESHING" and msg.get("attempt_id") == s.attempt_id:
            # btn_not_found/no_frame 只是这一帧没检出，交给 refresh.timeout 重试；只有发送失败才立即判死
            if msg.get("reason") == "post_failed":
                await _need_manual(s)
    elif typ == "window.unavailable":
        if msg.get("reason") in ("closed", "replaced"):
            await close_session(s, "window_closed")
    if rid:
        await ws.send_json({"type": "event.ack", "request_id": rid})

# ---------- scanner WebSocket ----------
@app.websocket("/ws/scan")
async def scan_ws(ws: WebSocket):
    login = auth.get_login(ws.cookies.get(COOKIE_NAME))
    if not login or login.role != "scanner":
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.scan_sockets.add(ws)
    sid_cookie = ws.cookies.get(COOKIE_NAME)
    ws.scope["drq_sid"] = sid_cookie
    subs: dict[str, BizSession] = {}
    try:
        await ws.send_json(_broadcast_pending())
        while True:
            msg = await ws.receive_json()
            if not auth.get_login(sid_cookie):
                await ws.close(code=4401); return
            typ = msg.get("type")
            if typ == "ping":
                await ws.send_json({"type": "pong"}); continue
            sid = msg.get("session_id", "")
            s = state.get(sid) if sid else None
            if typ == "subscribe" and s:
                subs[s.id] = s; s.subscribers.add(ws)
                await ws.send_json({"type": "session.snapshot", "session_id": s.id, "state": s.state,
                                    "count": s.refresh_count, "qr_jpeg": s.qr_jpeg if s.state == "VALID" else None})
            elif typ == "unsubscribe" and s:
                s.subscribers.discard(ws); subs.pop(s.id, None)
            elif typ == "scanned" and s:
                if login.role == "scanner" and s.state in ("VALID", "REFRESHING"):
                    s.state = "SCANNED"; s.qr_jpeg = None
                    await broadcast_state(s); await broadcast_pending()
            elif typ == "reject" and s:
                if login.role == "scanner" and not s.is_terminal:
                    await close_session(s, "reject")
    except WebSocketDisconnect:
        pass
    finally:
        for s in subs.values():
            s.subscribers.discard(ws)
        hub.scan_sockets.discard(ws)
