# 抖店远程扫码登录助手

坐席电脑上打开抖店客户端，二维码实时出现在异地扫码人的网页里；扫码人直接用手机抖店 App 扫码，不需要任何人截图、转发链接或输入取件码。

## 组成

| 目录 | 说明 |
| --- | --- |
| `server/` | FastAPI 服务端：三套账号（admin/seat/scanner）、业务会话状态机、WebSocket 中继、管理接口 |
| `scan-web/` | 扫码端网页：登录、待扫码列表、实时二维码、我已扫码/拒绝/刷新 |
| `admin-web/` | 管理员网页：账号改密、在线坐席、强制下线、当前会话 |
| `agent-rs/` | **Windows 坐席端（Rust）**：WGC 抓帧、QR 识别、PostMessage 点击、系统托盘 + 本地网页面板，单文件 exe 不依赖 Python |
| `agent/` | 早期 Python 版 Agent（保留参考，正式交付用 `agent-rs/`） |
| `shared/` | 协议字段常量 |
| `deploy/` | nginx / systemd / 启动脚本 |
| `docs/` | 使用手册、部署手册、运维手册 |

## 快速开始

### 1. 服务端

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-server.txt
cp .env.example .env   # 修改 BASE_URL / SECRET_KEY / DATABASE_PATH
python -m server.init_db   # 打印 admin/seat/scanner 初始密码
bash deploy/start.sh
```

打开 `https://你的域名/admin`，用 admin 登录并修改 seat / scanner 密码。

### 2. 扫码端

浏览器打开 `https://你的域名/scan`，用 scanner 账号登录。坐席发起登录后，列表自动出现。

### 3. 坐席端（Windows）

直接双击 `DoudianRemoteQR.exe`（单文件，无需 Python）。  
程序常驻托盘，双击托盘图标打开本地面板；填写服务器地址、seat 密码、坐席名称、店铺名，点「发起登录」。

详见 [docs/USAGE.md](docs/USAGE.md) 与 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 构建 Windows 坐席端 exe（Rust）

```powershell
powershell -ExecutionPolicy Bypass -File deploy\build_agent.ps1
# 输出 dist\DoudianRemoteQR.exe（单文件，内置全部依赖，目标电脑无需 Python）
# 双击后常驻系统托盘（无控制台窗口）；若图标在任务栏 ^ 溢出区，拖到任务栏即可
# 双击托盘图标打开本地面板 http://127.0.0.1:8765/
```

## 测试

```bash
.venv/bin/python -m pytest tests -q
```

## 边界

- 不自动登录、不代填账号密码、不调用抖店 API。
- 只转发屏幕上显示的二维码截图 + 后台点击"刷新"按钮。
- 单进程单 worker；重启后业务会话与登录会话失效。
