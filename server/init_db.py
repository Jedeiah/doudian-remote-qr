import os, secrets
from . import accounts
from .db import init_schema
from .config import DB_PATH

def main():
    init_schema()
    created = []
    for username, role in (("admin", "admin"), ("seat", "seat"), ("scanner", "scanner")):
        if not accounts.get_account(username):
            pwd = os.getenv(username.upper() + "_PASSWORD") or secrets.token_urlsafe(12)
            accounts.create_account(username, pwd, role, must_change=(role == "admin"))
            created.append((username, pwd))
    if created:
        print("=" * 56)
        for u, p in created:
            print(f"{u} 初始密码 = {p}")
        print("请登录 /admin 修改 seat/scanner 密码，并修改 admin 密码")
        print("=" * 56)
    else:
        print("数据库已初始化：", DB_PATH)

if __name__ == "__main__":
    main()
