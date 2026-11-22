#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
exec .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port "${PORT:-8000}" --workers 1
