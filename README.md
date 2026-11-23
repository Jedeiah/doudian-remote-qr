# 抖店远程扫码登录助手

坐席电脑上打开抖店客户端停在扫码登录页，二维码会实时出现在异地扫码人的网页里；扫码人用手机抖店 App 扫码即可，**不需要截图、转发链接或输入取件码**。

## 它是怎么工作的

三端协作，服务端只做中继和状态管理，**不接触账号密码、不调用抖店 API**：

1. Windows 坐席端抓取抖店客户端窗口上的二维码，实时推给服务端；二维码过期时自动识别刷新按钮并点击。
2. 服务端把二维码转发给扫码端网页，驱动一个会话状态机（等待二维码 → 有效 → 自动刷新中 → 已扫码待确认 → 完成）。
3. 扫码人用手机扫码后，在网页点「我已扫码」，坐席确认成功即结束本单。

## 组成

| 目录 | 说明 |
| --- | --- |
| `server/` | FastAPI 服务端：三套账号（admin/seat/scanner）、业务会话状态机、WebSocket 中继、管理接口。会话按 `operation_id` 幂等 |
| `scan-web/` | 扫码端网页：登录、待扫码列表、实时二维码、我已扫码 / 拒绝（**无手动刷新**，过期由坐席端自动处理） |
| `admin-web/` | 管理员网页：账号改密、在线坐席、强制下线、当前会话 |
| `agent-rs/` | **Windows 坐席端（Rust）**：WGC 抓帧、QR 识别、PostMessage 点击、系统托盘 + 本地网页面板，单文件 exe 不依赖 Python |
| `agent/` | 早期 Python 版 Agent（保留参考，正式交付用 `agent-rs/`） |
| `shared/` | 前后端协议字段常量 |
| `deploy/` | nginx / systemd / 构建脚本 |
| `docs/` | 使用手册、部署手册 |

## 快速开始

### 1. 服务端（Linux，Python 3.12）

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-server.txt
cp .env.example .env
# 编辑 .env：BASE_URL、SECRET_KEY（openssl rand -hex 32）、DATABASE_PATH
python -m server.init_db   # 首次启动打印 admin/seat/scanner 初始密码
bash deploy/start.sh       # 监听 127.0.0.1:8000，配合 nginx 反代 + HTTPS
```

打开 `https://你的域名/admin`，用 admin 登录并修改 seat / scanner 密码（改完已登录端会掉线）。生产部署细节见 [docs/DEPLOY.md](docs/DEPLOY.md)。

> **必须单 worker**：登录会话和业务会话都在内存里，多 worker 会导致不同进程看到不同状态。`deploy/start.sh` 和 systemd 单元都已固定 `--workers 1`。重启后所有会话失效，两端需重新登录。

### 2. 扫码端

浏览器打开 `https://你的域名/scan`，用 scanner 账号登录。坐席发起登录后，列表自动出现。选一条会话，用**手机上的抖店 App** 扫码（不是显示网页的那台设备），确认后点「我已扫码」。只有手机时可用「保存二维码」再经相册识别。

完整操作步骤见 [docs/USAGE.md](docs/USAGE.md)。

### 3. 坐席端（Windows）

双击 `DoudianRemoteQR.exe`（单文件，无需 Python 或任何运行时）。程序常驻系统托盘，双击托盘图标打开本地面板 `http://127.0.0.1:8765/`，填服务器地址、seat 账号密码、坐席名称，点「发起登录」。

同时让抖店客户端**退出登录、停在扫码登录页，窗口不要最小化**。同一坐席一次只能进行一单，完成或取消后可再发起。

## 构建 Windows 坐席端 exe（Rust）

在装有 Rust 工具链的机器上（Windows 原生 MSVC，或 Linux 配 mingw-w64 交叉编译）：

```bash
# Windows 原生
powershell -ExecutionPolicy Bypass -File deploy\build_agent.ps1

# Linux 交叉编译（需 x86_64-pc-windows-gnu target 与 mingw-w64）
cd agent-rs && cargo build --release --target x86_64-pc-windows-gnu
```

产物为单文件 exe（内置全部依赖），双击后常驻系统托盘，本地面板 `http://127.0.0.1:8765/`。

## 测试

```bash
.venv/bin/python -m pytest tests -q
```

现有测试覆盖账号、状态基础路径与鉴权；WebSocket 双端、状态机完整流转属于运行时联调范畴，见 `docs/` 与部署环境实测。

## 边界

- 不自动登录、不代填账号密码、不调用抖店 API。
- 只转发屏幕上显示的二维码截图 + 后台点击「刷新」按钮。
- 二维码过期由坐席端自动处理，扫码端没有手动刷新按钮。
- 单进程单 worker；重启后业务会话与登录会话失效。
- 会话按 `operation_id` 幂等：重复发起同一单不会建出多条会话。
