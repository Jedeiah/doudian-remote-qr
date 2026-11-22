import os, tempfile
os.environ.setdefault("DATABASE_PATH", tempfile.mktemp(suffix=".db"))
from server import state

def test_create_and_pending():
    s = state.create("测试店铺", "seat-1", "坐席01", "1:2", 2, 1)
    assert s.state == "WAIT_QR"
    assert any(x["session_id"] == s.id for x in state.pending_list())
    state.remove(s.id)

def test_shop_key_normalized():
    assert state.shop_key(" 测试 店铺 ") == state.shop_key("测试 店铺")

def test_active_for_seat():
    s = state.create("店铺A", "seat-x", "坐席X", "1:2", 2, 1)
    assert len(state.active_for_seat("seat-x")) == 1
    s.state = "CLOSED"
    assert len(state.active_for_seat("seat-x")) == 0
    state.remove(s.id)
