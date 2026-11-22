import os, tempfile
os.environ.setdefault("DATABASE_PATH", tempfile.mktemp(suffix=".db"))
from server import accounts
from server.db import init_schema

def setup_module(module):
    init_schema()
    if not accounts.get_account("u1"):
        accounts.create_account("u1", "Passw0rd!123", "seat")

def test_password_hash_roundtrip():
    a = accounts.get_account("u1")
    assert accounts.verify_password(a["password_hash"], "Passw0rd!123")
    assert not accounts.verify_password(a["password_hash"], "wrong")

def test_set_password_invalidates_old():
    accounts.set_password("u1", "NewPassw0rd!456")
    a = accounts.get_account("u1")
    assert accounts.verify_password(a["password_hash"], "NewPassw0rd!456")
    assert not accounts.verify_password(a["password_hash"], "Passw0rd!123")

def test_seat_unique_name():
    acc = accounts.get_account("u1")
    sid1 = accounts.ensure_seat(acc["id"], "坐席03", "pc-A")
    sid2 = accounts.ensure_seat(acc["id"], "坐席03", "pc-A")
    assert sid1 == sid2
    try:
        accounts.ensure_seat(acc["id"], "坐席03", "pc-B")
        assert False, "should reject different fingerprint"
    except ValueError:
        pass
