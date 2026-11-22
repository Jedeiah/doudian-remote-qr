use anyhow::{anyhow, Result};
use base64::{engine::general_purpose::STANDARD, Engine};
use image::{ImageBuffer, Luma, Rgba};
use serde_json::{json, Value};
use std::sync::mpsc::{channel, sync_channel, Receiver, SyncSender};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tungstenite::{client::IntoClientRequest, Message};

#[derive(Clone)]
struct FrameData { w: u32, h: u32, rgba: Vec<u8> }

#[cfg(windows)]
struct Capture { tx: SyncSender<FrameData>, closed: std::sync::Arc<std::sync::atomic::AtomicBool> }

#[cfg(windows)]
impl windows_capture::capture::GraphicsCaptureApiHandler for Capture {
    type Flags = (SyncSender<FrameData>, std::sync::Arc<std::sync::atomic::AtomicBool>);
    type Error = Box<dyn std::error::Error + Send + Sync>;
    fn new(ctx: windows_capture::capture::Context<Self::Flags>) -> Result<Self, Self::Error> {
        Ok(Self { tx: ctx.flags.0.clone(), closed: ctx.flags.1.clone() })
    }
    fn on_frame_arrived(&mut self, frame: &mut windows_capture::frame::Frame, _c: windows_capture::graphics_capture_api::InternalCaptureControl) -> Result<(), Self::Error> {
        let w = frame.width(); let h = frame.height();
        let mut buf = frame.buffer()?;
        let data = buf.as_nopadding_buffer()?;
        let _ = self.tx.try_send(FrameData { w, h, rgba: data.to_vec() });
        Ok(())
    }
    fn on_closed(&mut self) -> Result<(), Self::Error> {
        self.closed.store(true, std::sync::atomic::Ordering::SeqCst);
        Ok(())
    }
}

fn http_json(method: &str, url: &str, cookie: &str, body: Option<Value>) -> Result<(String, Value)> {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(3))
        .timeout_read(Duration::from_secs(8))
        .timeout_write(Duration::from_secs(8))
        .build();
    let mut req = agent.request(method, url);
    if !cookie.is_empty() { req = req.set("Cookie", cookie); }
    let resp = match body { Some(b) => req.set("Content-Type", "application/json").send_string(&b.to_string()), None => req.call() };
    match resp {
        Ok(r) => {
            let set_cookie = r.header("set-cookie").unwrap_or("").split(';').next().unwrap_or("").to_string();
            let text = r.into_string().unwrap_or_default();
            Ok((set_cookie, serde_json::from_str(&text).unwrap_or(Value::Null)))
        }
        Err(ureq::Error::Status(code, r)) => { let t = r.into_string().unwrap_or_default(); Err(anyhow!("HTTP {code}: {t}")) }
        Err(e) => Err(anyhow!("HTTP error: {e}")),
    }
}

fn ws_connect(url: &str, cookie: &str) -> Result<tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>> {
    let mut req = url.into_client_request()?;
    req.headers_mut().insert("Cookie", cookie.parse()?);
    let (ws, _) = tungstenite::connect(req)?;
    Ok(ws)
}

fn roi(w: u32, h: u32) -> (u32, u32, u32, u32) { (w / 2, h * 30 / 100, w * 92 / 100, h * 72 / 100) }

fn find_blue_button(f: &FrameData) -> Option<(f64, f64, u32, u32)> {
    let (x0, y0, x1, y1) = roi(f.w, f.h);
    let (mut minx, mut miny, mut maxx, mut maxy, mut count) = (u32::MAX, u32::MAX, 0u32, 0u32, 0u32);
    for y in y0..y1 { for x in x0..x1 {
        let i = ((y * f.w + x) * 4) as usize;
        if i + 3 >= f.rgba.len() { continue; }
        let r = f.rgba[i] as i32; let g = f.rgba[i+1] as i32; let b = f.rgba[i+2] as i32;
        if b > 150 && b > r + 40 && b > g + 20 && g > 40 {
            count += 1; minx = minx.min(x); miny = miny.min(y); maxx = maxx.max(x); maxy = maxy.max(y);
        }
    }}
    if count < 800 { return None; }
    let w = maxx - minx + 1; let h = maxy - miny + 1;
    let aspect = w as f64 / h as f64;
    if !(1.6..=4.5).contains(&aspect) || w < 80 || h < 24 { return None; }
    Some(((minx + maxx) as f64 / 2.0, (miny + maxy) as f64 / 2.0, w, h))
}

fn decode_qr(f: &FrameData) -> Option<(String, [f64; 2])> {
    let (x0, y0, x1, y1) = roi(f.w, f.h);
    let rw = x1 - x0; let rh = y1 - y0;
    let mut luma = Vec::with_capacity((rw * rh) as usize);
    for y in y0..y1 { for x in x0..x1 {
        let i = ((y * f.w + x) * 4) as usize;
        let v = if i + 2 < f.rgba.len() {
            let r = f.rgba[i] as u32; let g = f.rgba[i+1] as u32; let b = f.rgba[i+2] as u32;
            ((r * 299 + g * 587 + b * 114) / 1000) as u8
        } else { 255 };
        luma.push(v);
    }}
    let img: ImageBuffer<Luma<u8>, Vec<u8>> = ImageBuffer::from_raw(rw, rh, luma)?;
    let mut prepared = rqrr::PreparedImage::prepare(img);
    for g in prepared.detect_grids() {
        if let Ok((_m, text)) = g.decode() {
            let cx = g.bounds.iter().map(|p| p.x as f64).sum::<f64>() / 4.0;
            let cy = g.bounds.iter().map(|p| p.y as f64).sum::<f64>() / 4.0;
            return Some((text, [cx, cy]));
        }
    }
    None
}

fn crop_jpeg(f: &FrameData, cx: f64, cy: f64) -> Result<String> {
    let (x0, y0, _, _) = roi(f.w, f.h);
    let gx = x0 as f64 + cx; let gy = y0 as f64 + cy; let half = (f.w.min(f.h) as f64 * 0.19).max(190.0).min(480.0);
    let left = (gx - half).max(0.0) as u32; let top = (gy - half).max(0.0) as u32;
    let right = (gx + half).min(f.w as f64) as u32; let bottom = (gy + half).min(f.h as f64) as u32;
    let img: ImageBuffer<Rgba<u8>, Vec<u8>> = ImageBuffer::from_raw(f.w, f.h, f.rgba.clone()).ok_or_else(|| anyhow!("bad frame"))?;
    let sub = image::imageops::crop_imm(&img, left, top, right - left, bottom - top).to_image();
    let rgb = image::DynamicImage::ImageRgba8(sub).to_rgb8();
    let mut jpg = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut jpg, 78).encode_image(&rgb)?;
    Ok(format!("data:image/jpeg;base64,{}", STANDARD.encode(jpg)))
}

fn post_click(hwnd: isize, cx: f64, cy: f64) -> bool {
    #[cfg(windows)]
    { crate::win::click(hwnd, cx as i32, cy as i32) }
    #[cfg(not(windows))]
    { let _ = (hwnd, cx, cy); false }
}

fn emit(v: Value) {
    use std::io::Write;
    let mut out = std::io::stdout();
    let _ = writeln!(out, "{}", v);
    let _ = out.flush();
}

pub fn run_worker() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let op = args.iter().position(|a| a == "--operation-id").and_then(|i| args.get(i + 1)).cloned().unwrap_or_default();
    let result = run_worker_inner(&op);
    if let Err(e) = &result {
        emit(json!({"type":"session.failed","operation_id":op,"detail":format!("{e:#}")}));
    }
    result
}

fn run_worker_inner(operation_id: &str) -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let get = |k: &str| args.iter().position(|a| a == k).and_then(|i| args.get(i + 1)).cloned();
    let server = get("--server").ok_or_else(|| anyhow!("missing --server"))?;
    let shop = get("--shop").ok_or_else(|| anyhow!("missing --shop"))?;
    let username = get("--username").unwrap_or_else(|| "seat".into());
    let password = get("--password").unwrap_or_default();
    let seat_name = get("--seat-name").unwrap_or_default();
    let hwnd_arg = get("--hwnd").and_then(|s| s.parse::<isize>().ok());
    let fingerprint = format!("{}:rust", std::env::var("COMPUTERNAME").unwrap_or_else(|_| "pc".into()));

    let (cookie, login) = if let Ok(c) = std::env::var("DRQ_COOKIE") {
        let (_h, me) = http_json("GET", &format!("{server}/auth/me"), &c, None)?;
        (c, me)
    } else {
        http_json("POST", &format!("{server}/auth/login"), "", Some(json!({
            "username": username, "password": password, "role": "seat", "seat_name": seat_name, "device_fingerprint": fingerprint
        })))?
    };
    let seat_id = login["seat_id"].as_str().unwrap_or("").to_string();
    if seat_id.is_empty() { return Err(anyhow!("login failed: {login}")); }
    let hwnd = hwnd_arg.or_else(crate::win::find_window).ok_or_else(|| anyhow!("未找到抖店窗口，请先打开抖店客户端"))?;
    if crate::win::is_iconic(hwnd) {
        crate::win::restore(hwnd);
        std::thread::sleep(Duration::from_millis(400));
        if crate::win::is_iconic(hwnd) {
            return Err(anyhow!("抖店窗口处于最小化且无法自动恢复，请手动恢复后再发起登录"));
        }
    }
    let pid = crate::win::window_pid(hwnd);
    let closed = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let (frame_tx, frame_rx): (SyncSender<FrameData>, Receiver<FrameData>) = sync_channel(2);
    #[cfg(windows)]
    {
        use windows_capture::capture::GraphicsCaptureApiHandler;
        use windows_capture::settings::{ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings, MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings};
        use windows_capture::window::Window;
        let window = Window::from_raw_hwnd(hwnd as *mut std::ffi::c_void);
        let settings = Settings::new(window, CursorCaptureSettings::Default, DrawBorderSettings::Default, SecondaryWindowSettings::Default, MinimumUpdateIntervalSettings::Default, DirtyRegionSettings::Default, ColorFormat::Rgba8, (frame_tx.clone(), closed.clone()));
        let closed2 = closed.clone();
        std::thread::spawn(move || { if let Err(e) = Capture::start(settings) { crate::win::log(&format!("capture error: {e}")); closed2.store(true, std::sync::atomic::Ordering::SeqCst); } });
    }
    // 等首帧（最多 3 秒）；抓帧失败直接失败，不能创建“没有码”的幽灵会话
    if frame_rx.recv_timeout(Duration::from_secs(3)).is_err() {
        return Err(anyhow!("capture: no first frame"));
    }
    let (_c, sess) = http_json("POST", &format!("{server}/sessions"), &cookie, Some(json!({
        "shop_name": shop, "window_key": format!("{pid}:{hwnd}"), "hwnd": hwnd, "pid": pid
    })))?;
    let sid = sess["session_id"].as_str().unwrap_or("").to_string();
    let mut attempt = sess["attempt_id"].as_str().unwrap_or("").to_string();
    if sid.is_empty() { return Err(anyhow!("create session failed: {sess}")); }
    emit(json!({"type":"session.created","operation_id":operation_id,"session_id":sid,"attempt_id":attempt}));
    crate::win::log(&format!("session {sid}"));


    let ws_url = server.replace("https://", "wss://").replace("http://", "ws://") + "/ws/agent";
    let mut ws0 = ws_connect(&ws_url, &cookie)?;
    match ws0.get_mut() {
        tungstenite::stream::MaybeTlsStream::Plain(s) => { let _ = s.set_read_timeout(Some(Duration::from_millis(80))); }
        tungstenite::stream::MaybeTlsStream::NativeTls(t) => { let _ = t.get_ref().set_read_timeout(Some(Duration::from_millis(80))); }
        _ => {}
    }
    let ws = Arc::new(Mutex::new(ws0));
    ws.lock().unwrap().send(Message::Text(json!({"type":"agent.hello","seat_id":seat_id}).to_string().into()))?;
    let ws_read = ws.clone();
    let (cmd_tx, cmd_rx) = channel::<Value>();
    std::thread::spawn(move || {
        let mut idle = 0u32;
        loop {
            let msg = { let mut g = ws_read.lock().unwrap(); g.read() };
            match msg {
                Ok(Message::Text(t)) => { idle = 0; if let Ok(v) = serde_json::from_str::<Value>(&t) { let _ = cmd_tx.send(v); } }
                Ok(_) => { idle = 0; }
                Err(tungstenite::Error::Io(e)) if e.kind() == std::io::ErrorKind::WouldBlock || e.kind() == std::io::ErrorKind::TimedOut => {
                    idle += 1;
                    if idle > 1500 { let _ = cmd_tx.send(json!({"type":"ws_closed"})); break; }
                    continue;
                }
                Err(_) => { let _ = cmd_tx.send(json!({"type":"ws_closed"})); break; },
            }
        }
    });
    let send = |v: Value| { let _ = ws.lock().unwrap().send(Message::Text(v.to_string().into())); };

    let mut last_digest = String::new();
    let mut last_sent = std::time::Instant::now().checked_sub(Duration::from_secs(120)).unwrap_or_else(std::time::Instant::now);
    let mut btn_present = false;
    let mut had_qr = false;
    let mut no_qr_frames = 0u32;
    let mut last_ping = std::time::Instant::now();
    loop {
        if last_ping.elapsed() > Duration::from_secs(20) {
            let _ = ws.lock().unwrap().send(Message::Ping(Vec::new().into()));
            last_ping = std::time::Instant::now();
        }
        if closed.load(std::sync::atomic::Ordering::SeqCst) {
            send(json!({"type":"window.unavailable","session_id":sid,"reason":"closed"}));
            return Ok(());
        }
        while let Ok(cmd) = cmd_rx.try_recv() {
            match cmd["type"].as_str().unwrap_or("") {
                "cmd.refresh" => {
                    attempt = cmd["attempt_id"].as_str().unwrap_or(&attempt).to_string();
                    std::thread::sleep(Duration::from_millis(400));
                    let mut frame_opt = frame_rx.recv_timeout(Duration::from_secs(2)).ok();
                    // 丢掉积压帧，只用最新一帧定位按钮
                    while let Ok(f2) = frame_rx.try_recv() { frame_opt = Some(f2); }
                    if frame_opt.is_none() {
                        send(json!({"type":"click.rejected","session_id":sid,"request_id":format!("r{}", now_ms()),"attempt_id":attempt,"reason":"no_frame"}));
                        continue;
                    }
                    if let Some(frame) = frame_opt {
                        if let Some((cx, cy, _, _)) = find_blue_button(&frame) {
                            // 整帧尺寸必须等于窗口外框；客户区偏移由系统实测，做一次平移
                            let (ww, wh) = crate::win::window_size(hwnd);
                            if (ww as i32 - frame.w as i32).abs() > 2 || (wh as i32 - frame.h as i32).abs() > 2 {
                                crate::win::log(&format!("geometry mismatch: window {}x{} frame {}x{}", ww, wh, frame.w, frame.h));
                                send(json!({"type":"click.rejected","session_id":sid,"request_id":format!("r{}", now_ms()),"attempt_id":attempt,"reason":"geometry_mismatch"}));
                                continue;
                            }
                            let (dx, dy) = match crate::win::client_offset(hwnd) {
                                Some(v) => v,
                                None => {
                                    send(json!({"type":"click.rejected","session_id":sid,"request_id":format!("r{}", now_ms()),"attempt_id":attempt,"reason":"client_origin_failed"}));
                                    continue;
                                }
                            };
                            let (cw, ch) = crate::win::client_size(hwnd);
                            let px = cx - dx as f64;
                            let py = cy - dy as f64;
                            if px < 0.0 || py < 0.0 || px >= cw as f64 || py >= ch as f64 {
                                send(json!({"type":"click.rejected","session_id":sid,"request_id":format!("r{}", now_ms()),"attempt_id":attempt,"reason":"out_of_client"}));
                                continue;
                            }
                            crate::win::log(&format!("click frame {} {} -> client {} {} (client {}x{} frame {}x{})", cx, cy, px, py, cw, ch, frame.w, frame.h));
                            let ok = post_click(hwnd, px as f64, py as f64);
                            if ok { send(json!({"type":"click.sent","session_id":sid,"request_id":format!("c{}", now_ms()),"attempt_id":attempt})); }
                            else { send(json!({"type":"click.rejected","session_id":sid,"request_id":format!("c{}", now_ms()),"attempt_id":attempt,"reason":"post_failed"})); }
                        } else {
                            send(json!({"type":"click.rejected","session_id":sid,"request_id":format!("r{}", now_ms()),"attempt_id":attempt,"reason":"btn_not_found"}));
                        }
                    }
                }
                "cmd.arm" => { attempt = cmd["attempt_id"].as_str().unwrap_or(&attempt).to_string(); }
                "cmd.rearm" => { btn_present = false; }
                "ws_closed" => { let _ = http_json("POST", &format!("{server}/sessions/{sid}/cancel"), &cookie, None); return Ok(()); }
                "force.logout" => return Ok(()),
                "state" if cmd["session_id"] == sid && matches!(cmd["state"].as_str(), Some("DONE") | Some("CLOSED")) => return Ok(()),
                _ => {}
            }
        }
        let frame = match frame_rx.recv_timeout(Duration::from_millis(300)) {
            Ok(f) => f,
            Err(_) => continue,
        };
        // 每轮只处理最新一帧，避免陈旧帧导致刷新超时
        let mut frame = frame;
        while let Ok(f2) = frame_rx.try_recv() { frame = f2; }
        let mut decoded = false;
        if let Some((text, center)) = decode_qr(&frame) {
            decoded = true; had_qr = true; no_qr_frames = 0;
            let digest = format!("c:{}", sha256_text(&text));
            let due = digest != last_digest || last_sent.elapsed() >= Duration::from_secs(55);
            if due && last_sent.elapsed() >= Duration::from_secs(1) {
                if let Ok(jpg) = crop_jpeg(&frame, center[0], center[1]) {
                    send(json!({"type":"qr.detected","session_id":sid,"request_id":format!("q{}", now_ms()),
                        "jpg":jpg,"digest":digest,"attempt_id":attempt,"captured_at":now_ms()}));
                    last_digest = digest; last_sent = std::time::Instant::now();
                    crate::win::log(&format!("qr {} {}", text.len(), center[0]));
                }
            }
        } else {
            no_qr_frames += 1;
        }
        // 二维码解码与蓝块检测是独立的：过期码可能仍可解码，必须仍能发现刷新按钮
        if let Some((cx, cy, _, _)) = find_blue_button(&frame) {
            if (had_qr || no_qr_frames > 10) && !btn_present {
                btn_present = true;
                send(json!({"type":"btn.detected","session_id":sid,"request_id":format!("b{}", now_ms()),
                    "btn_rel":[cx / frame.w as f64, cy / frame.h as f64],"frame_w":frame.w,"frame_h":frame.h,"dpi":crate::win::dpi_of(hwnd)}));
                crate::win::log(&format!("btn {} {} frame {}x{}", cx, cy, frame.w, frame.h));
            }
            continue;
        }
        if decoded { btn_present = false; }
    }
}

fn sha256_text(s: &str) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut h = DefaultHasher::new(); s.hash(&mut h); format!("{:x}", h.finish())
}
fn now_ms() -> u128 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0) }
