import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from .db import connect

_ph = PasswordHasher()

def hash_password(password: str) -> str:
    return _ph.hash(password)

def verify_password(hash_: str, password: str) -> bool:
    try:
        return _ph.verify(hash_, password)
    except Exception:
        return False

def get_account(username: str):
    with connect() as con:
        row = con.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None

def create_account(username: str, password: str, role: str, must_change: bool = False):
    with connect() as con:
        con.execute(
            "INSERT INTO accounts(username,password_hash,role,must_change_password) VALUES(?,?,?,?)",
            (username, hash_password(password), role, 1 if must_change else 0),
        )

def set_password(username: str, password: str, must_change: bool = False):
    with connect() as con:
        cur = con.execute(
            "UPDATE accounts SET password_hash=?, must_change_password=?, updated_at=? WHERE username=?",
            (hash_password(password), 1 if must_change else 0, datetime.now(timezone.utc).isoformat(), username),
        )
        return cur.rowcount > 0

def list_accounts():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT username,role,must_change_password,updated_at FROM accounts ORDER BY id")]

def ensure_seat(account_id: int, seat_name: str, fingerprint: str):
    """Return seat_id for this seat_name. Reject if name bound to different fingerprint."""
    with connect() as con:
        row = con.execute("SELECT * FROM seats WHERE seat_name=?", (seat_name,)).fetchone()
        if row:
            if row["account_id"] != account_id:
                raise ValueError("seat_name_bound_to_other_account")
            if row["device_fingerprint"] and fingerprint and row["device_fingerprint"] != fingerprint:
                raise ValueError("seat_name_bound_to_other_device")
            con.execute("UPDATE seats SET last_seen_at=? WHERE seat_id=?", (datetime.now(timezone.utc).isoformat(), row["seat_id"]))
            return row["seat_id"]
        seat_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO seats(seat_id,seat_name,account_id,device_fingerprint,last_seen_at) VALUES(?,?,?,?,?)",
            (seat_id, seat_name, account_id, fingerprint, datetime.now(timezone.utc).isoformat()),
        )
        return seat_id

def list_seats():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM seats ORDER BY seat_name")]

def delete_seat(seat_id: str):
    with connect() as con:
        con.execute("DELETE FROM seats WHERE seat_id=?", (seat_id,))

def reset_admin_password(new_password: str):
    with connect() as con:
        row = con.execute("SELECT id FROM accounts WHERE username='admin' AND role='admin'").fetchone()
        if not row:
            create_account("admin", new_password, "admin", must_change=True)
        else:
            set_password("admin", new_password, must_change=True)
