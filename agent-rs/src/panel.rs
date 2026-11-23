use anyhow::{anyhow, Result};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use tiny_http::{Header, Method, Response, Server};

pub struct PanelServer;

// 单次操作的全部状态收口到一把锁：id/phase/session/error/deadline 一起读写，
// 杜绝 check-then-write 被其他线程插入导致的状态覆盖。
#[derive(Clone, Default)]
struct Op {
    id: String,
    phase: String,          // "" / starting / running / failed
    session_id: Option<String>,
    error: String,
    deadline: Option<std::time::Instant>,
}

#[derive(Clone, Default)]
struct State {
    cookie: String,
    server: String,
    op: Arc<Mutex<Op>>,
    // op_id -> worker 子进程；便于超时精确 kill，避免误杀其他 operation
    children: Arc<Mutex<HashMap<String, std::process::Child>>>,
}

const CSS: &str = r#"<style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f4f7fb;color:#10233b;min-height:100vh}
.wrap{max-width:900px;margin:0 auto;padding:26px 20px}.card{background:#fff;border-radius:18px;box-shadow:0 14px 40px rgba(24,50,90,.10);padding:20px;margin-bottom:16px}
h1{font-size:20px;margin:0 0 4px}p.sub{color:#6b7c92;font-size:13px;margin:0 0 16px}
.row{display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;margin-bottom:10px}label{font-size:13px;font-weight:600;color:#334155}input{height:42px;border:1px solid #e5ecf5;border-radius:11px;padding:0 12px;font-size:14px;width:100%}
.btn{border:0;border-radius:11px;height:40px;padding:0 15px;font-size:13.5px;font-weight:700;cursor:pointer;margin-right:8px}.primary{background:linear-gradient(135deg,#2563eb,#0ea5e9);color:#fff}.ghost{background:#fff;border:1px solid #e5ecf5;color:#334155}.danger{background:#fff1f2;border:1px solid #fecdd3;color:#be123c}.btn[disabled]{opacity:.45}
.login-wrap{min-height:100vh;display:grid;place-items:center;padding:24px}.login-card{width:100%;max-width:420px;padding:32px 28px}
.brand{display:flex;gap:12px;align-items:center}.logo{width:44px;height:44px;border-radius:14px;background:linear-gradient(135deg,#2563eb,#0ea5e9);display:grid;place-items:center;color:#fff;font-weight:800}
.sessions{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}.session{border:1px solid #e5ecf5;border-radius:14px;padding:12px}.session h3{font-size:15px;margin:0 0 4px}.session-actions{display:flex;gap:8px;margin-top:8px}.session-actions .btn{flex:1;margin:0;height:42px;padding:0 8px;white-space:nowrap;font-size:13px}.m{font-size:12px;color:#6b7c92;margin-bottom:8px}
.qr{display:grid;place-items:center;min-height:150px;background:#f8fbff;border:1px solid #e0edff;border-radius:10px}.qr img{width:150px;height:150px;object-fit:contain;background:#fff;padding:6px}
.err{color:#be123c;font-size:13px;margin-top:8px}.notice{margin-top:12px;padding:12px 14px;border-radius:12px;background:#fffbeb;border:1px solid #fcd34d;color:#92400e;font-size:14px;font-weight:700;display:none}.notice.show{display:block}
</style>"#;

fn login_html() -> String {
    format!(r#"<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>坐席端登录</title>{CSS}</head><body><div class="login-wrap"><div class="card login-card"><div class="brand"><div class="logo">码</div><div><h1>抖店扫码助手</h1><p class="sub" style="margin:2px 0 0">坐席端 · 登录</p></div></div><h1 style="margin-top:24px">坐席登录</h1><p class="sub">登录后即可发起扫码；店铺名称在功能页每次输入</p>
<div class="row"><label>服务器地址</label><input id="server" value="" placeholder="https://your-domain.example"></div>
<div class="row"><label>坐席账号</label><input id="username" value="seat"></div>
<div class="row"><label>密码</label><input id="password" type="password"></div>
<div class="row"><label>坐席名称</label><input id="seat_name" value="坐席01"></div>
<button class="btn primary" style="width:100%;height:44px" id="login">登 录</button><div class="err" id="err"></div>
<p style="font-size:12px;color:#94a3b8;margin-top:18px">一个坐席账号只需登录一次；之后可在功能页多次发起不同店铺</p></div></div>
<script>const $=s=>document.querySelector(s);$('#login').onclick=async()=>{{const sv=$('#server').value.trim();if(!/^https?:\/\//.test(sv)){{$('#err').textContent='服务器地址需以 http:// 或 https:// 开头';return}}try{{const r=await fetch('/api/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{server:sv,username:$('#username').value,password:$('#password').value,seat_name:$('#seat_name').value}})}});const j=await r.json();if(!r.ok)throw new Error(j.detail||'登录失败');location.href='/app'}}catch(e){{$('#err').textContent=e.message}}}};</script></body></html>"#)
}

fn app_html() -> String {
    format!(r#"<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>坐席端</title>{CSS}</head><body><div class="wrap">
<div class="card" style="display:flex;justify-content:space-between;align-items:center"><div class="brand"><div class="logo">码</div><div><h1>抖店扫码助手</h1><p class="sub" style="margin:2px 0 0">坐席端 · 发起扫码</p></div></div><button class="btn ghost" id="logout">退出登录</button></div>
<div id="notice" class="notice"></div>
<div class="card"><h1 style="font-size:17px">发起扫码</h1><p class="sub">每次扫码前输入店铺名称；同一账号可多次发起不同店铺（一次一个，完成或取消后可再发起）</p>
<div class="row"><label>店铺名称</label><input id="shop" placeholder="例如：轻禾户外钓鱼服"></div>
<div class="row"><label>窗口句柄</label><input id="hwnd" placeholder="留空自动识别抖店窗口"></div>
<button class="btn primary" id="start">发起登录</button><div class="err" id="err"></div></div>
<div class="card"><div id="sessions" class="sessions"></div></div></div>
<script>const $=s=>document.querySelector(s);const st={{WAIT_QR:'等待二维码',VALID:'二维码已生成',REFRESHING:'自动刷新中',SCANNED:'已扫码待确认'}};let busy=false;function esc(t){{return String(t??'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]))}}
async function api(p,o){{const r=await fetch(p,Object.assign({{headers:{{'Content-Type':'application/json'}}}},o||{{}}));const j=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(j.detail||'请求失败');return j}}
$('#start').onclick=async()=>{{const b=$('#start');if(b.disabled)return;b.disabled=true;b.textContent='发起中…';try{{await api('/api/start',{{method:'POST',body:JSON.stringify({{shop:$('#shop').value,hwnd:$('#hwnd').value}})}});$('#err').textContent='正在启动坐席端，请稍候…';$('#shop').value=''}}catch(e){{$('#err').textContent=e.message;b.disabled=false;b.textContent='发起登录'}}}};
$('#logout').onclick=async()=>{{await api('/api/logout',{{method:'POST'}});location.href='/login'}};
async function tick(){{try{{const j=await api('/api/status');if(!j.logged_in){{location.href='/login';return}}if(j.starting){{$('#start').disabled=true;$('#start').textContent='发起中…';$('#err').textContent='正在启动坐席端，请稍候…'}}else{{$('#start').disabled=false;$('#start').textContent='发起登录'}}if(j.start_error){{$('#err').textContent=j.start_error}}if(j.error){{$('#err').textContent=j.error;return}}const list=j.sessions||[];if(!list.length){{$('#sessions').innerHTML='<div class="m">暂无进行中的会话</div>';$('#notice').className='notice';document.title='抖店扫码助手 · 坐席端';return}}let scanned=list.find(x=>x.state==='SCANNED');if(scanned){{$('#notice').textContent='扫码端已标记「'+scanned.shop_name+'」已扫码，请确认抖店是否登录成功；成功点确认，未成功点取消';$('#notice').className='notice show';document.title='【待确认】'+scanned.shop_name}}else{{$('#notice').className='notice';document.title='抖店扫码助手 · 坐席端'}}
$('#sessions').innerHTML=list.map(s=>`<div class="session" data-id="${{esc(s.session_id)}}"><h3>${{esc(s.shop_name)}}</h3><div class="m">${{st[s.state]||s.state}} · 第 ${{s.count}} 次刷新</div><div class="qr">${{s.qr_jpeg?`<img src="${{s.qr_jpeg}}">`:'<span class="m">无二维码</span>'}}</div><div class="session-actions"><button class="btn primary" ${{['VALID','SCANNED'].includes(s.state)?'':'disabled'}} onclick="confirmS('${{s.session_id}}')">确认登录成功</button><button class="btn danger" onclick="cancelS('${{s.session_id}}')">登录未成功，取消</button></div></div>`).join('')}}catch(e){{}}}}
window.confirmS=async id=>{{if(busy)return;busy=true;document.querySelectorAll('#sessions button').forEach(b=>b.disabled=true);try{{await api('/api/confirm',{{method:'POST',body:JSON.stringify({{session_id:id}})}});document.querySelector(`.session[data-id="${{id}}"]`)?.remove();await tick()}}catch(e){{const m=String(e.message||'');if(m.includes('404')||m.includes('not_found')){{document.querySelector(`.session[data-id="${{id}}"]`)?.remove();await tick()}}else{{alert(m)}}}}finally{{busy=false;document.querySelectorAll('#sessions button').forEach(b=>b.disabled=false)}}}};
window.cancelS=async id=>{{if(busy)return;busy=true;document.querySelectorAll('#sessions button').forEach(b=>b.disabled=true);try{{await api('/api/cancel',{{method:'POST',body:JSON.stringify({{session_id:id}})}});document.querySelector(`.session[data-id="${{id}}"]`)?.remove();await tick()}}catch(e){{const m=String(e.message||'');if(m.includes('404')||m.includes('not_found')){{document.querySelector(`.session[data-id="${{id}}"]`)?.remove();await tick()}}else{{alert(m)}}}}finally{{busy=false;document.querySelectorAll('#sessions button').forEach(b=>b.disabled=false)}}}};
setInterval(tick,800);tick();</script></body></html>"#)
}

fn respond_json(req: tiny_http::Request, code: u16, v: Value) {
    let body = v.to_string();
    let _ = req.respond(Response::from_string(body).with_status_code(code).with_header(Header::from_bytes("Content-Type", "application/json").unwrap()));
}

fn read_json(req: &mut tiny_http::Request) -> Value {
    let mut s = String::new();
    let _ = req.as_reader().read_to_string(&mut s);
    serde_json::from_str(&s).unwrap_or(Value::Null)
}

fn http(method: &str, url: &str, cookie: &str, body: Option<Value>) -> Result<(String, Value)> {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(std::time::Duration::from_secs(3))
        .timeout_read(std::time::Duration::from_secs(8))
        .timeout_write(std::time::Duration::from_secs(8))
        .build();
    let mut r = agent.request(method, url);
    if !cookie.is_empty() { r = r.set("Cookie", cookie); }
    let resp = match body { Some(b) => r.set("Content-Type", "application/json").send_string(&b.to_string()), None => r.call() };
    match resp {
        Ok(resp) => {
            let c = resp.header("set-cookie").unwrap_or("").split(';').next().unwrap_or("").to_string();
            let t = resp.into_string().unwrap_or_default();
            Ok((c, serde_json::from_str(&t).unwrap_or(Value::Null)))
        }
        Err(ureq::Error::Status(c, r)) => { let t = r.into_string().unwrap_or_default(); Err(anyhow!("{c}: {t}")) }
        Err(e) => Err(anyhow!("{e}")),
    }
}

pub fn start_server() -> Result<PanelServer> {
    let server = Arc::new(Server::http("127.0.0.1:8765").map_err(|e| anyhow!("{e}"))?);
    let state = Arc::new(Mutex::new(State::default()));

    // 后台回收已退出的 worker 子进程，避免内核进程对象/句柄随多次登录累积泄漏
    {
        let children = state.lock().unwrap().children.clone();
        std::thread::spawn(move || loop {
            std::thread::sleep(std::time::Duration::from_secs(3));
            let mut guard = children.lock().unwrap();
            guard.retain(|_, c| !matches!(c.try_wait(), Ok(Some(_)) | Err(_)));
        });
    }
    let srv = server.clone();
    std::thread::spawn(move || {
        for mut req in srv.incoming_requests() {
            let path = req.url().split('?').next().unwrap_or("").to_string();
            let method = req.method().clone();
            let host_ok = req.headers().iter().find(|h| h.field.equiv("Host"))
                .map(|h| { let v=h.value.as_str(); v=="127.0.0.1:8765" || v=="localhost:8765" })
                .unwrap_or(false);
            if !host_ok {
                let _ = req.respond(Response::from_string("forbidden").with_status_code(403));
                continue;
            }
            if method == Method::Post {
                let ct_ok = req.headers().iter().find(|h| h.field.equiv("Content-Type"))
                    .map(|h| h.value.as_str().to_ascii_lowercase().starts_with("application/json"))
                    .unwrap_or(false);
                if !ct_ok {
                    let _ = req.respond(Response::from_string("unsupported media type").with_status_code(415));
                    continue;
                }
                if let Some(h) = req.headers().iter().find(|h| h.field.equiv("Origin")) {
                    let o = h.value.as_str();
                    if o != "http://127.0.0.1:8765" && o != "http://localhost:8765" {
                        let _ = req.respond(Response::from_string("forbidden origin").with_status_code(403));
                        continue;
                    }
                }
            }
            match (method, path.as_str()) {
                (Method::Get, "/") | (Method::Get, "/login") => {
                    let _ = req.respond(Response::from_string(login_html()).with_header(Header::from_bytes("Content-Type", "text/html; charset=utf-8").unwrap()).with_header(Header::from_bytes("X-Frame-Options", "DENY").unwrap()).with_header(Header::from_bytes("Cache-Control", "no-store").unwrap()));
                }
                (Method::Get, "/app") => {
                    let logged = !state.lock().unwrap().cookie.is_empty();
                    if !logged {
                        let _ = req.respond(Response::empty(302).with_header(Header::from_bytes("Location", "/login").unwrap()));
                    } else {
                        let _ = req.respond(Response::from_string(app_html()).with_header(Header::from_bytes("Content-Type", "text/html; charset=utf-8").unwrap()).with_header(Header::from_bytes("X-Frame-Options", "DENY").unwrap()).with_header(Header::from_bytes("Cache-Control", "no-store").unwrap()));
                    }
                }
                (Method::Get, "/api/status") => {
                    let st = state.lock().unwrap().clone();
                    if st.cookie.is_empty() { respond_json(req, 200, json!({"logged_in": false, "sessions": []})); continue; }
                    // HTTP 前记录 op.id：has 是网络快照，只有与 op.id 同代才可用，
                    // 否则（请求期间 op 被换成新的）整轮丢弃 has 判定，避免旧快照套新 op。
                    let observed_op_id = st.op.lock().unwrap().id.clone();
                    match http("GET", &format!("{}/sessions/current", st.server), &st.cookie, None) {
                        Ok((_, v)) => {
                            // 在 op 单锁内完成判定与状态改写；需要 kill 的 child 先移出，锁外再 wait
                            let mut child_to_kill: Option<std::process::Child> = None;
                            let mut timed_out_op_id: Option<String> = None;
                            let (phase, start_error, session_id) = {
                                let mut op = st.op.lock().unwrap();
                                if op.id != observed_op_id {
                                    // 请求期间 op 已变化，has 快照过期，本轮不做任何基于 has 的状态改写
                                    (op.phase.clone(), op.error.clone(), op.session_id.clone())
                                } else {
                                // 只认 operation_id 等于当前 op 的会话：别人的会话不能把本 op 标成 running，
                                // 也不能用通用 has 阻止本 op 超时。必须在 op 锁内、用当前 op.id 计算。
                                let cur_op_id = op.id.clone();
                                let has_current = v["sessions"].as_array().map(|items| {
                                    items.iter().any(|s| s["operation_id"].as_str() == Some(cur_op_id.as_str()))
                                }).unwrap_or(false);
                                if op.phase == "starting" && !has_current && op.deadline.map(|t| t <= std::time::Instant::now()).unwrap_or(true) {
                                    let op_id = op.id.clone();
                                    timed_out_op_id = Some(op_id.clone());
                                    child_to_kill = st.children.lock().unwrap().remove(&op_id);
                                    op.id = String::new();
                                    op.deadline = None;
                                    op.phase = "failed".to_string();
                                    op.error = "启动超时，请查看 agent.log".to_string();
                                }
                                // 服务端已有本 op 的会话但 stdout 的 session.created 尚未被 reader 消费时，
                                // 靠 HTTP /sessions/current 把 starting 纠正为 running，避免面板一直显示“启动中”
                                if op.phase == "starting" && has_current {
                                    op.phase = "running".to_string();
                                    op.deadline = None;
                                    if op.session_id.is_none() {
                                        if let Some(mine) = v["sessions"].as_array().and_then(|items| {
                                            items.iter().find(|s| s["operation_id"].as_str() == Some(cur_op_id.as_str()))
                                        }) {
                                            op.session_id = mine["session_id"].as_str().map(str::to_string);
                                        }
                                    }
                                }
                                if op.phase == "running" && !has_current {
                                    let op_id = op.id.clone();
                                    child_to_kill = st.children.lock().unwrap().remove(&op_id);
                                    *op = Op::default();
                                }
                                    (op.phase.clone(), op.error.clone(), op.session_id.clone())
                                }
                            };
                            if let Some(mut c) = child_to_kill { let _ = c.kill(); let _ = c.wait(); }
                            if let Some(old_op_id) = timed_out_op_id {
                                // 只取消 operation_id 等于旧 op 的会话：清掉旧 worker 的孤儿，
                                // 不碰新 op 的会话。按 op_id 过滤把误清新会话的窗口关掉；
                                // 但仍非绝对零孤儿——旧 worker 若在 GET 后 cancel 前又建会话可能漏。
                                let server = st.server.clone();
                                let cookie = st.cookie.clone();
                                std::thread::spawn(move || {
                                    std::thread::sleep(std::time::Duration::from_millis(300));
                                    if let Ok((_, v)) = http("GET", &format!("{}/sessions/current", server), &cookie, None) {
                                        if let Some(items) = v["sessions"].as_array() {
                                            for s in items {
                                                if s["operation_id"].as_str() == Some(old_op_id.as_str()) {
                                                    if let Some(sid) = s["session_id"].as_str() {
                                                        let _ = http("POST", &format!("{}/sessions/{}/cancel", server, sid), &cookie, None);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                });
                            }
                            let starting = phase == "starting";
                            respond_json(req, 200, json!({"logged_in": true, "sessions": v["sessions"], "starting": starting,
                                "start_error": start_error, "operation": {"phase": phase, "session_id": session_id}}))
                        },
                        Err(e) if e.to_string().starts_with("401") => respond_json(req, 200, json!({"logged_in": false, "sessions": []})),
                        Err(e) => respond_json(req, 200, json!({"logged_in": true, "sessions": [], "error": e.to_string()})),
                    }
                }
                (Method::Post, "/api/login") => {
                    let b = read_json(&mut req);
                    let server = b["server"].as_str().unwrap_or("").trim_end_matches('/').to_string();
                    match http("POST", &format!("{server}/auth/login"), "", Some(json!({
                        "username": b["username"], "password": b["password"], "role": "seat",
                        "seat_name": b["seat_name"], "device_fingerprint": format!("{}:rust", std::env::var("COMPUTERNAME").unwrap_or_else(|_| "pc".into()))
                    }))) {
                        Ok((cookie, _)) => {
                            let mut st = state.lock().unwrap(); st.cookie = cookie; st.server = server;
                            respond_json(req, 200, json!({"ok": true}));
                        }
                        Err(e) => respond_json(req, 400, json!({"detail": e.to_string()})),
                    }
                }
                (Method::Post, "/api/start") => {
                    let b = read_json(&mut req);
                    let st = state.lock().unwrap().clone();
                    if st.cookie.is_empty() { respond_json(req, 400, json!({"detail":"请先登录"})); continue; }
                    if b["shop"].as_str().unwrap_or("").trim().is_empty() { respond_json(req, 400, json!({"detail":"请输入店铺名称"})); continue; }
                    let cur_phase = st.op.lock().unwrap().phase.clone();
                    if cur_phase == "starting" { respond_json(req, 409, json!({"detail":"正在发起中，请稍候"})); continue; }
                    if cur_phase == "running" { respond_json(req, 409, json!({"detail":"已有进行中的会话，请先完成或取消"})); continue; }
                    let hwnd: isize = match b["hwnd"].as_str().and_then(|h| h.trim().parse::<isize>().ok()) {
                        Some(h) => h,
                        None => match crate::win::find_window() {
                            Some(h) if crate::win::is_iconic(h) => {
                                crate::win::restore(h);
                                std::thread::sleep(std::time::Duration::from_millis(400));
                                if crate::win::is_iconic(h) { respond_json(req, 400, json!({"detail":"抖店窗口最小化且无法自动恢复，请手动恢复后再发起"})); continue; }
                                h
                            }
                            Some(h) => h,
                            None => { respond_json(req, 400, json!({"detail":"未找到抖店窗口，请先打开抖店客户端"})); continue; }
                        },
                    };
                    let exe = std::env::current_exe().unwrap_or_default();
                    let nanos = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
                    let operation_id = format!("op-{}-{}", std::process::id(), nanos);
                    let mut cmd = std::process::Command::new(exe);
                    cmd.arg("worker").arg("--server").arg(&st.server).arg("--username").arg("seat").arg("--password").arg("").arg("--seat-name").arg("").arg("--shop").arg(b["shop"].as_str().unwrap_or(""));
                    cmd.arg("--hwnd").arg(hwnd.to_string());
                    cmd.arg("--operation-id").arg(&operation_id);
                    // 显式开关：只有面板启动的 worker 才从 stdin 读 cookie，手动运行不会阻塞
                    cmd.arg("--cookie-stdin");
                    cmd.stdin(Stdio::piped());
                    // 单锁写入新 op 状态
                    {
                        let mut op = st.op.lock().unwrap();
                        op.id = operation_id.clone();
                        op.phase = "starting".to_string();
                        op.session_id = None;
                        op.error = String::new();
                        op.deadline = Some(std::time::Instant::now() + std::time::Duration::from_secs(20));
                    }
                    let server = st.server.clone();
                    let cookie = st.cookie.clone();
                    cmd.stdout(Stdio::piped());
                    cmd.stderr(Stdio::null());
                    let op_id_thread = operation_id.clone();
                    let op = st.op.clone();
                    let children = st.children.clone();
                    std::thread::spawn(move || {
                        if let Ok((_, v)) = http("GET", &format!("{}/sessions/current", server), &cookie, None) {
                            if v["sessions"].as_array().map(|a| !a.is_empty()).unwrap_or(false) {
                                let mut g = op.lock().unwrap();
                                if g.id == op_id_thread {
                                    g.error = "本坐席已有进行中的会话，请在列表中处理或取消后再发起".to_string();
                                    g.phase = "failed".to_string();
                                    g.deadline = None;
                                    g.id = String::new();
                                }
                                return;
                            }
                        }
                        // spawn 前二次校验：若本 op 已被超时/confirm/cancel/logout 撤销，不再启动
                        {
                            let g = op.lock().unwrap();
                            if g.id != op_id_thread || g.phase != "starting" { return; }
                        }
                        match cmd.spawn() {
                            Ok(mut child) => {
                                // 先不写 cookie：worker 会阻塞在 stdin，确保“注册 child + op 校验”先完成
                                let stdin = child.stdin.take();
                                let stdout = child.stdout.take();
                                {
                                    let g = op.lock().unwrap();
                                    if g.id != op_id_thread || g.phase != "starting" {
                                        drop(g);
                                        let _ = child.kill();
                                        let _ = child.wait();
                                        return;
                                    }
                                    children.lock().unwrap().insert(op_id_thread.clone(), child);
                                }
                                // 注册完成后才下发 cookie；若超时先发生，child 已被 kill，不会建会话
                                if let Some(mut stdin) = stdin {
                                    use std::io::Write;
                                    let _ = writeln!(stdin, "{}", cookie);
                                }
                                let op2 = op.clone();
                                std::thread::spawn(move || {
                                    let mut saw_event = false;
                                    if let Some(out) = stdout {
                                        for line in BufReader::new(out).lines().flatten() {
                                            let v: Value = match serde_json::from_str(&line) { Ok(v) => v, Err(_) => continue };
                                            if v["operation_id"].as_str().unwrap_or("") != op_id_thread { continue; }
                                            // id 校验 + 状态写入在同一把 op 锁内完成，不可被其他线程插入
                                            let mut g = op2.lock().unwrap();
                                            if g.id != op_id_thread { break; }
                                            match v["type"].as_str().unwrap_or("") {
                                                "session.created" => {
                                                    saw_event = true;
                                                    g.session_id = v["session_id"].as_str().map(str::to_string);
                                                    g.phase = "running".to_string();
                                                    g.deadline = None;
                                                }
                                                "session.failed" => {
                                                    saw_event = true;
                                                    g.error = v["detail"].as_str().unwrap_or("坐席端启动失败").to_string();
                                                    g.phase = "failed".to_string();
                                                    g.deadline = None;
                                                }
                                                _ => {}
                                            }
                                        }
                                    }
                                    // stdout EOF：worker 在创建会话前就退出/崩溃且没有发任何事件时，
                                    // 立即置 failed。同样在 op 单锁内判定，仅当前 op 且仍 starting 才处理。
                                    if !saw_event {
                                        let mut g = op2.lock().unwrap();
                                        if g.id == op_id_thread && g.phase == "starting" {
                                            g.error = "worker 在创建会话前退出，请查看 agent.log".to_string();
                                            g.phase = "failed".to_string();
                                            g.deadline = None;
                                        }
                                    }
                                });
                            }
                            Err(e) => {
                                let mut g = op.lock().unwrap();
                                if g.id == op_id_thread {
                                    g.error = format!("启动坐席端失败：{e}");
                                    g.phase = "failed".to_string();
                                    g.deadline = None;
                                }
                            }
                        }
                    });
                    respond_json(req, 202, json!({"ok": true, "starting": true}));
                }
                (Method::Post, "/api/confirm") | (Method::Post, "/api/cancel") => {
                    let b = read_json(&mut req);
                    let st = state.lock().unwrap().clone();
                    let sid = b["session_id"].as_str().unwrap_or("");
                    let action = if path.ends_with("confirm") { "confirm" } else { "cancel" };
                    match http("POST", &format!("{}/sessions/{}/{}", st.server, sid, action), &st.cookie, None) {
                        Ok(_) => {
                            // 清 op 并移出对应 child（锁外 kill/wait），防止旧 reader 复活已结束的会话
                            let mut g = st.op.lock().unwrap();
                            let op_id = g.id.clone();
                            *g = Op::default();
                            drop(g);
                            let child = st.children.lock().unwrap().remove(&op_id);
                            if let Some(mut c) = child { let _ = c.kill(); let _ = c.wait(); }
                            respond_json(req, 200, json!({"ok": true}))
                        },
                        Err(e) => respond_json(req, 400, json!({"detail": e.to_string()})),
                    }
                }
                (Method::Post, "/api/logout") => {
                    let st = state.lock().unwrap().clone();
                    let _ = http("POST", &format!("{}/auth/logout", st.server), &st.cookie, None);
                    // 先让当前 op 失效，阻止启动线程在 drain 之后插入 child；再 drain/kill
                    *st.op.lock().unwrap() = Op::default();
                    let kids: Vec<std::process::Child> = st.children.lock().unwrap().drain().map(|(_, c)| c).collect();
                    for mut c in kids { let _ = c.kill(); let _ = c.wait(); }
                    state.lock().unwrap().cookie.clear();
                    respond_json(req, 200, json!({"ok": true}));
                }
                _ => respond_json(req, 404, json!({"detail":"not found"})),
            }
        }
    });
    Ok(PanelServer)
}
