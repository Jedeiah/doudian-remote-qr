import argparse
import secrets
from . import accounts

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reset-password")
    r.add_argument("username")
    args = p.parse_args()
    if args.cmd == "reset-password":
        pwd = secrets.token_urlsafe(12)
        if not accounts.set_password(args.username, pwd, must_change=(args.username == "admin")):
            raise SystemExit("account not found")
        print("新密码 =", pwd)

if __name__ == "__main__":
    main()
