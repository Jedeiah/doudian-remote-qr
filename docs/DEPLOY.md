# 部署手册

## 服务器要求

- Ubuntu 22.04 / Debian 12（推荐），2 核 4G 20G 磁盘
- Python 3.12、Nginx、公网域名、HTTPS 证书

## 安装

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv nginx certbot python3-certbot-nginx
sudo mkdir -p /opt/doudian-remote-qr && cd /opt/doudian-remote-qr
# 上传代码后
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-server.txt
cp .env.example .env
# 修改 .env：BASE_URL、SECRET_KEY（openssl rand -hex 32）、DATABASE_PATH
python -m server.init_db
sudo chown -R www-data:www-data data
sudo cp deploy/doudian.service /etc/systemd/system/
sudo systemctl enable --now doudian
sudo cp deploy/nginx.conf /etc/nginx/sites-available/doudian
sudo ln -sf /etc/nginx/sites-available/doudian /etc/nginx/sites-enabled/doudian
sudo certbot --nginx -d 你的域名
sudo nginx -s reload
curl -I https://你的域名/health
```

## 运维

- 备份：每天备份 `data/app.db`。
- 日志：`journalctl -u doudian -n 200`。
- 升级：备份 DB → `systemctl stop doudian` → 换代码 → `pip install -r requirements-server.txt` → `systemctl start doudian`。
- 重启：所有业务会话和登录会话失效，两端需重新登录。
- 忘记 admin 密码：
  ```
  .venv/bin/python -m server.admin reset-password admin
  ```

## 单进程约束

必须保持 `--workers 1`。业务会话和登录会话都在内存；多 worker 会导致不同进程看到不同的会话状态。
