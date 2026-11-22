import os, tempfile
os.environ["DATABASE_PATH"] = tempfile.mktemp(suffix=".db")
os.environ["ADMIN_PASSWORD"] = "AdminPass!1234"
os.environ["SEAT_PASSWORD"] = "SeatPass!1234"
os.environ["SCANNER_PASSWORD"] = "ScanPass!1234"
from fastapi.testclient import TestClient
from server.main import app

def test_login_and_role_guard():
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"username": "admin", "password": "AdminPass!1234", "role": "admin"})
        assert r.status_code == 200
        assert r.json()["must_change_password"] is True
        assert c.get("/admin/accounts").status_code == 403
        r = c.post("/auth/change-password", json={"old_password": "AdminPass!1234", "new_password": "AdminNewPass!1234"})
        assert r.status_code == 200
        r = c.post("/auth/login", json={"username": "admin", "password": "AdminNewPass!1234", "role": "admin"})
        assert r.status_code == 200
        r = c.get("/admin/accounts")
        assert r.status_code == 200
        names = [x["username"] for x in r.json()["items"]]
        assert {"admin", "seat", "scanner"} <= set(names)

def test_seat_login_gets_seat_id():
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"username": "seat", "password": "SeatPass!1234",
                                        "role": "seat", "seat_name": "坐席01", "device_fingerprint": "pc1"})
        assert r.status_code == 200
        assert r.json()["seat_id"]

def test_scanner_cannot_admin():
    with TestClient(app) as c:
        c.post("/auth/login", json={"username": "scanner", "password": "ScanPass!1234", "role": "scanner"})
        assert c.get("/admin/accounts").status_code == 401
