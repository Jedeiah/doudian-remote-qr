import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "app.db")))
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PORT = int(os.getenv("PORT", "8000"))
SECRET_KEY = os.getenv("SECRET_KEY", "")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "12"))
BUSINESS_TTL_MINUTES = int(os.getenv("BUSINESS_TTL_MINUTES", "10"))
WAIT_QR_SECONDS = int(os.getenv("WAIT_QR_SECONDS", "120"))
COOKIE_NAME = "drq_sid"
