"""Windows system tray for the agent. Runs pystray in the main thread."""
from __future__ import annotations
import threading
import webbrowser

PANEL_URL = "http://127.0.0.1:8765/"

def run_tray(on_quit=None):
    import pystray
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=14, fill="#2563eb")
    d.rounded_rectangle([18, 18, 46, 46], radius=4, outline="white", width=5)
    def open_panel(icon=None, item=None):
        webbrowser.open(PANEL_URL)
    def quit_app(icon, item):
        if on_quit:
            on_quit()
        icon.stop()
    menu = pystray.Menu(
        pystray.MenuItem("打开面板", open_panel, default=True),
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("DoudianRemoteQR", img, "抖店扫码助手 · 在线", menu)
    icon.run()
