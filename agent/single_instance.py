"""Windows single-instance guard using a named mutex."""
from __future__ import annotations
import ctypes
import os

ERROR_ALREADY_EXISTS = 183
_mutex = None

def acquire(name: str = "DoudianRemoteQR.Agent") -> bool:
    """Return True if this is the first instance. Keep the returned mutex alive."""
    global _mutex
    if os.name != "nt":
        return True
    user = os.getenv("USERNAME", "user")
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, f"Local\\{name}.{user}")
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS
