"""Single field contract for all messages. Agent, server and scan-web must use these names."""
from typing import Literal

ROLES = ("admin", "seat", "scanner")

# Agent -> Server
MSG_BTN_DETECTED = "btn.detected"
MSG_QR_DETECTED = "qr.detected"
MSG_CLICK_SENT = "click.sent"
MSG_CLICK_REJECTED = "click.rejected"
MSG_WINDOW_UNAVAILABLE = "window.unavailable"

# Server -> Agent
MSG_CMD_REFRESH = "cmd.refresh"
MSG_CMD_ARM = "cmd.arm"
MSG_CMD_CANCEL = "cmd.cancel"
MSG_CMD_REARM = "cmd.rearm"
MSG_FORCE_LOGOUT = "force.logout"
MSG_EVENT_ACK = "event.ack"

# Server -> scanner
MSG_SESSIONS = "sessions"
MSG_SESSION_CREATED = "session.created"
MSG_SESSION_UPDATED = "session.updated"
MSG_SESSION_REMOVED = "session.removed"
MSG_SESSION_SNAPSHOT = "session.snapshot"
MSG_STATE = "state"
MSG_FRAME = "frame"
MSG_DONE = "done"
MSG_CLOSED = "closed"

STATES = ("WAIT_QR", "VALID", "REFRESHING", "SCANNED", "NEED_MANUAL", "PENDING_REPLACE", "DONE", "CLOSED")
VIRTUAL_STATES = ("EXPIRED",)
