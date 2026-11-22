import asyncio
import hashlib
import secrets
import time
from typing import Optional
from .models import BizSession
from .config import BUSINESS_TTL_MINUTES, WAIT_QR_SECONDS

_sessions: dict[str, BizSession] = {}
_timers: dict[str, asyncio.Task] = {}

def new_id() -> str:
    return secrets.token_urlsafe(18)

def shop_key(name: str) -> str:
    return hashlib.sha256(" ".join(name.strip().lower().split()).encode()).hexdigest()

def create(shop_name, seat_id, seat_name, window_key, hwnd, pid, operation_id=None):
    sid = new_id()
    s = BizSession(id=sid, shop_name=shop_name, shop_key=shop_key(shop_name),
                   seat_id=seat_id, seat_name=seat_name, window_key=window_key,
                   hwnd=int(hwnd), pid=int(pid), attempt_id=new_id(), operation_id=operation_id)
    _sessions[sid] = s
    return s

def get(sid: str) -> Optional[BizSession]:
    return _sessions.get(sid)

def all_sessions():
    return list(_sessions.values())

def active_for_seat(seat_id: str):
    return [s for s in _sessions.values() if s.seat_id == seat_id and not s.is_terminal]

def pending_list():
    order = {"WAIT_QR": 0, "VALID": 1, "REFRESHING": 2, "NEED_MANUAL": 3, "SCANNED": 4}
    items = [s for s in _sessions.values() if s.state in order]
    items.sort(key=lambda s: (order[s.state], -s.created_at))
    return [{
        "session_id": s.id, "shop_name": s.shop_name, "seat_name": s.seat_name,
        "created_at": int(s.created_at * 1000), "state": s.state, "count": s.refresh_count,
    } for s in items]

def remove(sid: str):
    _sessions.pop(sid, None)
    t = _timers.pop(sid, None)
    if t and not t.done():
        t.cancel()

def schedule(sid: str, coro, delay: float):
    cancel_timer(sid)
    async def runner():
        try:
            await asyncio.sleep(delay)
            await coro()
        except asyncio.CancelledError:
            pass
    _timers[sid] = asyncio.create_task(runner())

def cancel_timer(sid: str):
    t = _timers.pop(sid, None)
    if t and not t.done():
        t.cancel()

def touch(s: BizSession):
    s.last_active = time.time()
