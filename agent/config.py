from __future__ import annotations
import json, os
from pathlib import Path

APP_NAME = "DoudianRemoteQR"
def config_dir() -> Path:
    base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p

def load() -> dict:
    f = config_dir() / "config.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}

def save(cfg: dict):
    (config_dir() / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
