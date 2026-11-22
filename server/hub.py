from typing import Any
from fastapi import WebSocket

# scanner sockets: one per logged-in browser tab
scan_sockets: set[WebSocket] = set()
# seat_id -> agent websocket
agent_sockets: dict[str, WebSocket] = {}

async def safe_send(ws: WebSocket, payload: dict[str, Any]):
    try:
        await ws.send_json(payload)
    except Exception:
        scan_sockets.discard(ws)
        for sid, sock in list(agent_sockets.items()):
            if sock is ws:
                agent_sockets.pop(sid, None)

async def send_to_scan(payload: dict[str, Any]):
    for ws in list(scan_sockets):
        await safe_send(ws, payload)

async def send_to_subscribers(session, payload: dict[str, Any]):
    for ws in list(session.subscribers):
        await safe_send(ws, payload)

async def send_to_agent(seat_id: str, payload: dict[str, Any]) -> bool:
    ws = agent_sockets.get(seat_id)
    if not ws:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        agent_sockets.pop(seat_id, None)
        return False


async def close_sids(sids: list[str]):
    for ws in list(scan_sockets):
        if ws.scope.get("drq_sid") not in sids:
            continue
        try:
            await ws.close(code=4401)
        except Exception:
            pass
        scan_sockets.discard(ws)
    for seat, ws in list(agent_sockets.items()):
        try:
            if ws.scope.get("drq_sid") in sids:
                await ws.close(code=4401)
                agent_sockets.pop(seat, None)
        except Exception:
            agent_sockets.pop(seat, None)
