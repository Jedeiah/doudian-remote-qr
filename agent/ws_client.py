from __future__ import annotations
import asyncio, json, ssl
import certifi
import websockets

class AgentWS:
    def __init__(self, url, cookie, seat_id):
        self.url = url
        self.cookie = cookie
        self.seat_id = seat_id
        self.ws = None
        self.queue = None
        self.on_command = None

    async def connect(self, queue):
        self.queue = queue
        kw = {"additional_headers": {"Cookie": self.cookie}, "max_size": 8 * 1024 * 1024}
        if self.url.startswith("wss://"):
            kw["ssl"] = ssl.create_default_context(cafile=certifi.where())
        self.ws = await websockets.connect(self.url, **kw)
        await self.ws.send(json.dumps({"type": "agent.hello", "seat_id": self.seat_id}))
        return self

    async def send(self, payload: dict):
        if self.ws:
            await self.ws.send(json.dumps(payload, ensure_ascii=False))

    async def recv_loop(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if msg.get("type") in ("cmd.refresh", "cmd.arm", "cmd.cancel", "cmd.rearm", "force.logout"):
                    if self.on_command:
                        await self.on_command(msg)
                else:
                    await self.queue.put(msg)
        except Exception as e:
            print("WS recv error:", repr(e), flush=True)
