"""Entry point: default = tray + local panel; 'worker' = one capture session."""
import os
import sys

def _setup_frozen_logging():
    if getattr(sys, "frozen", False):
        base = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "DoudianRemoteQR")
        os.makedirs(base, exist_ok=True)
        log = open(os.path.join(base, "agent.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = log
        sys.stderr = log

def _ensure_ca():
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except Exception:
        pass

def main():
    _setup_frozen_logging()
    _ensure_ca()
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        sys.argv.pop(1)
        from agent.main import main as worker_main
        worker_main()
        return

    import webbrowser
    from agent.single_instance import acquire
    if not acquire("DoudianRemoteQR.Panel"):
        webbrowser.open("http://127.0.0.1:8765/")
        return

    from agent.panel import start_server
    srv = start_server(open_browser=False)
    from agent.tray import run_tray
    def quit_all():
        try:
            srv.shutdown()
        except Exception:
            pass
    run_tray(on_quit=quit_all)

if __name__ == "__main__":
    main()
