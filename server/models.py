from dataclasses import dataclass, field
from typing import Optional
import time

@dataclass
class BizSession:
    id: str
    shop_name: str
    shop_key: str
    seat_id: str
    seat_name: str
    window_key: str
    hwnd: int
    pid: int
    state: str = "WAIT_QR"
    attempt_id: str = ""
    refresh_count: int = 0
    retry_failed: int = 0
    qr_jpeg: Optional[str] = None
    old_digest: Optional[str] = None
    click_acked: bool = False
    manual_done: bool = False
    pending_qr: Optional[dict] = None
    last_btn_full: Optional[list] = None
    btn_geom: Optional[list] = None
    last_btn_at: Optional[float] = None
    need_manual_since: Optional[float] = None
    previous_state: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    closed_reason: Optional[str] = None
    operation_id: Optional[str] = None
    subscribers: set = field(default_factory=set)

    @property
    def is_terminal(self):
        return self.state in ("DONE", "CLOSED")
