"""坐席端本地面板：登录页 + 功能页（127.0.0.1 本地网页）。"""
from __future__ import annotations
import json, os, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx

HOST, PORT = "127.0.0.1", 8765
STATE = {"cookie": "", "server": "http://127.0.0.1:8000", "procs": []}

CSS = """<style>
:root{--bg:#f4f7fb;--ink:#10233b;--muted:#6b7c92;--line:#e5ecf5}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:radial-gradient(900px 500px at 10% -10%,#dbeafe,transparent 55%),var(--bg);color:var(--ink);min-height:100vh}
.wrap{max-width:900px;margin:0 auto;padding:26px 20px}.card{background:#fff;border:1px solid #fff;border-radius:18px;box-shadow:0 14px 40px rgba(24,50,90,.10);padding:20px;margin-bottom:16px}
h1{font-size:20px;margin:0 0 4px}p.sub{color:var(--muted);font-size:13px;margin:0 0 16px}
.row{display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;margin-bottom:10px}label{font-size:13px;font-weight:600;color:#334155}input{height:42px;border:1px solid var(--line);border-radius:11px;padding:0 12px;font-size:14px;background:#fbfdff;outline:none;width:100%}
.btn{border:0;border-radius:11px;height:40px;padding:0 15px;font-size:13.5px;font-weight:700;cursor:pointer;margin-right:8px}.primary{background:linear-gradient(135deg,#2563eb,#0ea5e9);color:#fff}.ghost{background:#fff;border:1px solid var(--line);color:#334155}.danger{background:#fff1f2;border:1px solid #fecdd3;color:#be123c}.btn[disabled]{opacity:.45;cursor:not-allowed}
.login-wrap{min-height:100vh;display:grid;place-items:center;padding:24px}.login-card{width:100%;max-width:420px;padding:32px 28px}
.brand{display:flex;gap:12px;align-items:center}.logo{width:44px;height:44px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#0ea5e9);display:grid;place-items:center;color:#fff;font-weight:800}
.status{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600}.dot{width:9px;height:9px;border-radius:50%;background:#94a3b8}.dot.on{background:#10b981;box-shadow:0 0 0 4px rgba(16,185,129,.15)}
.sessions{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}.session{border:1px solid var(--line);border-radius:14px;padding:12px;background:#fff}.session h3{font-size:15px;margin:0 0 4px}.session .m{font-size:12px;color:var(--muted);margin-bottom:8px}.qr{display:grid;place-items:center;min-height:150px;background:#f8fbff;border:1px solid #e0edff;border-radius:10px}.qr img{width:150px;height:150px;object-fit:contain;background:#fff;padding:6px;border-radius:8px}
.err{color:#be123c;font-size:13px;margin-top:8px}
</style>"""

LOGIN = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>坐席端登录 · 抖店扫码助手</title>__CSS__</head>
<body><div class="login-wrap"><div class="card login-card"><div class="brand"><div class="logo">码</div><div><h1>抖店扫码助手</h1><p class="sub" style="margin:2px 0 0">坐席端 · 登录</p></div></div>
<h1 style="margin-top:24px">坐席登录</h1><p class="sub">登录后即可发起扫码；店铺名称在功能页每次输入</p>
<div class="row"><label>服务器地址</label><input id="server" value="http://127.0.0.1:8000"></div>
<div class="row"><label>坐席账号</label><input id="username" value="seat"></div>
<div class="row"><label>密码</label><input id="password" type="password"></div>
<div class="row"><label>坐席名称</label><input id="seat_name" value="坐席01"></div>
<button class="btn primary" style="width:100%;height:44px" id="login">登 录</button><div class="err" id="err"></div>
<p style="font-size:12px;color:#94a3b8;margin-top:18px">一个坐席账号只需登录一次；之后可在功能页多次发起不同店铺</p>
</div></div><script>
const $=s=>document.querySelector(s);$('#login').onclick=async()=>{try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({server:$('#server').value,username:$('#username').value,password:$('#password').value,seat_name:$('#seat_name').value})});const j=await r.json();if(!r.ok)throw new Error(j.detail||'登录失败');location.href='/app'}catch(e){$('#err').textContent=e.message}};
</script></body></html>"""

APP = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>坐席端 · 抖店扫码助手</title>__CSS__</head>
<body><div class="wrap"><div class="card" style="display:flex;justify-content:space-between;align-items:center"><div class="brand"><div class="logo">码</div><div><h1>抖店扫码助手</h1><p class="sub" style="margin:2px 0 0">坐席端 · 发起扫码</p></div></div><button class="btn ghost" id="logout">退出登录</button></div>
<div class="card"><h1 style="font-size:17px">发起扫码</h1><p class="sub">每次扫码前输入店铺名称；同一账号可多次发起不同店铺（一次一个，完成或取消后可再发起）</p>
<div class="row"><label>店铺名称</label><input id="shop" placeholder="例如：轻禾户外钓鱼服"></div>
<div class="row"><label>窗口句柄</label><input id="hwnd" placeholder="留空自动识别抖店窗口"></div>
<button class="btn primary" id="start">发起登录</button><div class="err" id="err"></div></div>
<div class="card"><div class="status"><span class="dot" id="dot"></span><span id="phase">加载中…</span></div><div id="sessions" class="sessions" style="margin-top:14px"></div></div>
</div><script>
const $=s=>document.querySelector(s);function esc(t){return String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function api(p,o){const r=await fetch(p,Object.assign({headers:{'Content-Type':'application/json'}},o||{}));const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||'请求失败');return j}
$('#start').onclick=async()=>{try{await api('/api/start',{method:'POST',body:JSON.stringify({shop:$('#shop').value,hwnd:$('#hwnd').value})});$('#err').textContent='';$('#shop').value=''}catch(e){$('#err').textContent=e.message}};
$('#logout').onclick=async()=>{await api('/api/logout',{method:'POST'});location.href='/login'};
async function tick(){try{const j=await api('/api/status');if(!j.logged_in){location.href='/login';return}$('#dot').className='dot on';$('#phase').textContent='已登录 · 可多次发起';const list=j.sessions||[];if(!list.length){$('#sessions').innerHTML='<div class="m">暂无进行中的会话</div>';return}
$('#sessions').innerHTML=list.map(s=>`<div class="session"><h3>${esc(s.shop_name)}</h3><div class="m">${s.state} · 第 ${s.count} 次刷新</div><div class="qr">${s.qr_jpeg?`<img src="${s.qr_jpeg}">`:'<span class="m">无二维码</span>'}</div><div style="margin-top:8px"><button class="btn primary" ${['VALID','SCANNED'].includes(s.state)?'':'disabled'} onclick="confirmS('${s.session_id}')">确认成功</button><button class="btn danger" onclick="cancelS('${s.session_id}')">取消</button></div></div>`).join('')}catch(e){}}
window.confirmS=async id=>{try{await api('/api/confirm',{method:'POST',body:JSON.stringify({session_id:id})})}catch(e){alert(e.message)}};
window.cancelS=async id=>{if(confirm('确定取消该会话？')){try{await api('/api/cancel',{method:'POST',body:JSON.stringify({session_id:id})})}catch(e){alert(e.message)}}};
setInterval(tick,1500);tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _json(self):
        n = int(self.headers.get("Content-Length", 0) or 0); return json.loads(self.rfile.read(n) or b"{}")
    def do_GET(self):
        if self.path in ("/", "/login"):
            return self._send((LOGIN.replace("__CSS__", CSS)).encode(), ctype="text/html; charset=utf-8")
        if self.path == "/app":
            if not STATE["cookie"]:
                self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return
            return self._send((APP.replace("__CSS__", CSS)).encode(), ctype="text/html; charset=utf-8")
        if self.path == "/api/status":
            if not STATE["cookie"]: return self._send({"logged_in": False, "sessions": []})
            try:
                r = httpx.get(STATE["server"] + "/sessions/current", headers={"Cookie": STATE["cookie"]}, timeout=5)
                return self._send({"logged_in": True, "sessions": r.json().get("sessions", [])})
            except Exception as e:
                return self._send({"logged_in": True, "sessions": [], "reason": str(e)})
        self._send({"detail": "not found"}, 404)
    def do_POST(self):
        try:
            b = self._json()
            if self.path == "/api/login":
                STATE["server"] = b["server"].rstrip("/")
                r = httpx.post(STATE["server"] + "/auth/login", json={"username": b["username"], "password": b["password"], "role": "seat", "seat_name": b["seat_name"], "device_fingerprint": os.getenv("COMPUTERNAME", "pc") + ":win"}, timeout=10)
                if r.status_code != 200: return self._send({"detail": r.json().get("detail", "登录失败")}, 400)
                STATE["cookie"] = r.headers.get("set-cookie", "").split(";", 1)[0]
                return self._send({"ok": True})
            if self.path == "/api/start":
                if not STATE["cookie"]: return self._send({"detail": "请先登录"}, 400)
                if not b.get("shop", "").strip(): return self._send({"detail": "请输入店铺名称"}, 400)
                if getattr(sys, "frozen", False):
                    args = [sys.executable, "worker", "--server", STATE["server"], "--username", "seat", "--password", "", "--seat-name", "", "--shop", b["shop"], "--no-single"]
                else:
                    args = [sys.executable, "-m", "agent.main", "--server", STATE["server"], "--username", "seat", "--password", "", "--seat-name", "", "--shop", b["shop"], "--no-single"]
                env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), DRQ_COOKIE=STATE["cookie"], DRQ_SERVER=STATE["server"])
                if str(b.get("hwnd", "")).strip().isdigit(): args += ["--hwnd", str(b["hwnd"]).strip()]
                STATE["procs"].append(subprocess.Popen(args, env=env))
                return self._send({"ok": True})
            if self.path in ("/api/confirm", "/api/cancel"):
                sid = b["session_id"]; action = "confirm" if self.path.endswith("confirm") else "cancel"
                r = httpx.post(f"{STATE['server']}/sessions/{sid}/{action}", headers={"Cookie": STATE["cookie"]}, timeout=10)
                return self._send({"ok": r.status_code == 200, "detail": r.text if r.status_code != 200 else ""})
            if self.path == "/api/logout":
                STATE["cookie"] = ""; return self._send({"ok": True})
            self._send({"detail": "not found"}, 404)
        except Exception as e:
            self._send({"detail": str(e)}, 400)


def start_server(open_browser=True):
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(f"http://{HOST}:{PORT}/",), daemon=True).start()
    return srv

def main():
    start_server(open_browser=True)
    print(f"坐席端面板：http://{HOST}:{PORT}/")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
