from __future__ import annotations
import hashlib
import cv2
import numpy as np

def crop_roi(frame: np.ndarray):
    h, w = frame.shape[:2]
    x0, x1 = int(w * 0.50), int(w * 0.92)
    y0, y1 = int(h * 0.30), int(h * 0.72)
    return frame[y0:y1, x0:x1].copy(), (x0, y0)

def find_solid_blue_rect(roi: np.ndarray):
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([95, 110, 100]), np.array([118, 255, 255]))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 800 or w < 80 or h < 24:
            continue
        aspect = w / float(h)
        if not (1.6 <= aspect <= 4.5):   # 刷新按钮是横向长条；二维码中央 logo 近似正方形
            continue
        if best is None or area > best[0]:
            best = (area, x, y, w, h, cents[i])
    if not best:
        return None
    area, x, y, w, h, c = best
    return type("Btn", (), {"cx": float(c[0]), "cy": float(c[1]), "x": x, "y": y, "w": w, "h": h})

def qr_digest(data: bytes | None, pts, roi):
    if data:
        return "c:" + hashlib.sha256(data).hexdigest()
    try:
        arr = cv2.resize(roi, (64, 64), interpolation=cv2.INTER_AREA)
        return "g:" + hashlib.sha256(arr.tobytes()).hexdigest()
    except Exception:
        return "g:unknown"

def valid_jpeg(data: bytes) -> bool:
    if not data or len(data) < 100:
        return False
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img is not None and img.shape[0] > 40 and img.shape[1] > 40

def crop_with_quiet_zone(frame: np.ndarray, pts_full, module_px=12):
    h, w = frame.shape[:2]
    xs = pts_full[:, 0]; ys = pts_full[:, 1]
    x0 = max(0, int(xs.min() - module_px * 4)); x1 = min(w, int(xs.max() + module_px * 4))
    y0 = max(0, int(ys.min() - module_px * 4)); y1 = min(h, int(ys.max() + module_px * 4))
    if x1 - x0 < 80 or y1 - y0 < 80:
        return None
    crop = frame[y0:y1, x0:x1].copy()
    ok, enc = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 78])
    if not ok:
        return None
    return enc.tobytes(), (x0, y0), pts_full - np.array([x0, y0]), module_px

def detect_qr(roi: np.ndarray):
    det = cv2.QRCodeDetector()
    data, pts, _ = det.detectAndDecode(roi)
    if pts is None:
        return None, None, None
    return (data.encode("utf-8") if data else None), pts[0], det
