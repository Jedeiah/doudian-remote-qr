import secrets
import time
from dataclasses import dataclass, field
from typing import Optional
from fastapi import Cookie, HTTPException, Request
from .config import COOKIE_NAME, SESSION_TTL_HOURS

@dataclass
class LoginSession:
    sid: str
    username: str
    role: str
    seat_id: Optional[str] = None
    seat_name: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    must_change_password: bool = False

    @property
    def expires_at(self) -> float:
        return self.created_at + SESSION_TTL_HOURS * 3600

_sessions: dict[str, LoginSession] = {}

def create_login(username, role, seat_id=None, seat_name=None, must_change=False) -> LoginSession:
    s = LoginSession(secrets.token_urlsafe(32), username, role, seat_id, seat_name, must_change_password=must_change)
    _sessions[s.sid] = s
    return s

def get_login(sid: str | None) -> LoginSession | None:
    if not sid:
        return None
    s = _sessions.get(sid)
    if not s:
        return None
    if time.time() > s.expires_at:
        _sessions.pop(sid, None)
        return None
    s.last_seen = time.time()
    return s

def delete_login(sid: str):
    _sessions.pop(sid, None)

def revoke_seat(seat_id: str) -> list[str]:
    removed = []
    for sid, s in list(_sessions.items()):
        if s.seat_id == seat_id:
            _sessions.pop(sid, None); removed.append(sid)
    return removed

def revoke_user(username: str) -> list[str]:
    removed = []
    for sid, s in list(_sessions.items()):
        if s.username == username:
            _sessions.pop(sid, None); removed.append(sid)
    return removed

def current_login(request: Request) -> LoginSession:
    s = get_login(request.cookies.get(COOKIE_NAME))
    if not s:
        raise HTTPException(status_code=401, detail="not_logged_in")
    return s

def require_role(role: str):
    def dep(request: Request) -> LoginSession:
        s = current_login(request)
        if s.role != role:
            raise HTTPException(status_code=403, detail="forbidden")
        return s
    return dep
