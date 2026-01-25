# gestureos_agent/qt_menu_overlay.py
# MODE radial overlay (separate process)
# - Click-through + topmost + no-activate
# - Qt logical coords (QCursor.pos / QGuiApplication.screens)
# - Center fixed on open
#
# Cyber VR "final" redesign:
# - Prism glass disc + thin segmented arcs + micro ticks + radar sweep + subtle noise
# - Stable hover (hold + debounce) to prevent flicker
#
# Output events:
#   evt_q.put_nowait({"type":"HOVER","value": <MODE or None>})

import os
import time
import math
import ctypes
from ctypes import wintypes

# ---------------- Win32 constants ----------------
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

user32 = ctypes.windll.user32


def _get_window_long_ptr(hwnd, idx):
    if hasattr(user32, "GetWindowLongPtrW"):
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        return user32.GetWindowLongPtrW(hwnd, idx)
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    return user32.GetWindowLongW(hwnd, idx)


def _set_window_long_ptr(hwnd, idx, value):
    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        return user32.SetWindowLongPtrW(hwnd, idx, ctypes.c_ssize_t(value))
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    return user32.SetWindowLongW(hwnd, idx, ctypes.c_long(value))


def _hwnd_int(x) -> int:
    try:
        if isinstance(x, int):
            return x
        v = ctypes.cast(x, ctypes.c_void_p).value
        return int(v or 0)
    except Exception:
        try:
            return int(x)
        except Exception:
            return 0


def _apply_win_exstyle(hwnd_int: int, click_through: bool):
    hwnd_int = _hwnd_int(hwnd_int)
    if not hwnd_int:
        return
    try:
        hwnd = wintypes.HWND(hwnd_int)
        ex = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
        ex |= (WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        if click_through:
            ex |= WS_EX_TRANSPARENT
        else:
            ex &= (~WS_EX_TRANSPARENT)
        _set_window_long_ptr(hwnd, GWL_EXSTYLE, ex)
    except Exception:
        pass


def _hex_to_rgb(color_hex: str):
    s = str(color_hex).lstrip("#")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return r, g, b


def _wrap360(deg: float) -> float:
    d = deg % 360.0
    return d + 360.0 if d < 0 else d


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def run_menu_process(cmd_q, evt_q):
    if os.name != "nt":
        return

    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtGui import QCursor, QGuiApplication
    except Exception:
        return

    DEBUG = (os.getenv("HUD_DEBUG", "0") == "1")

    # ---------------- CONFIG ----------------
    MENU_SIZE = 560

    # disc / rings
    OUTER_R = MENU_SIZE * 0.475
    ARC_R = OUTER_R - 22
    ARC_THICK = 9                 # thin
    ARC_GAP_DEG = 11.0            # modern segmentation

    # hover stability
    DEADZONE_R = 44
    HOVER_MAX_R = OUTER_R - 8
    HOLD_SECONDS = 0.32           # keep last non-null a bit (prevents pinch timing null)
    DEBOUNCE_SECONDS = 0.06       # stabilize hover

    # labels
    LABEL_R = OUTER_R - 60
    LABEL_W = 158
    LABEL_H = 34

    # items (output)
    ITEMS = ["PRESENTATION", "MOUSE", "KEYBOARD", "VKEY", "DRAW"]
    N = len(ITEMS)
    START_ANG = -90.0  # top
    STEP = 360.0 / N

    MODE_ACCENT = {
        "MOUSE": "#00ffa6",
        "DRAW": "#ffb020",
        "PRESENTATION": "#3aa0ff",
        "KEYBOARD": "#b26bff",
        "VKEY": "#39ff9a",
        "DEFAULT": "#00ffa6",
    }

    # base palette
    COL_BG_A = QtGui.QColor(10, 16, 22, 190)
    COL_BG_B = QtGui.QColor(7, 11, 16, 130)
    COL_EDGE = QtGui.QColor(160, 210, 255, 86)
    COL_TEXT = QtGui.QColor(235, 248, 255, 245)
    COL_SUBT = QtGui.QColor(210, 235, 255, 190)

    def desktop_union_rect():
        rect = QtCore.QRect()
        for s in QGuiApplication.screens():
            g = s.geometry()
            rect = rect.united(g) if not rect.isNull() else QtCore.QRect(g)
        if rect.isNull():
            rect = QtCore.QRect(0, 0, 1920, 1080)
        return rect

    def clamp_window(x, y, w, h):
        r = desktop_union_rect()
        min_x = r.left()
        min_y = r.top()
        max_x = r.right() - w
        max_y = r.bottom() - h
        x = max(min_x, min(int(x), int(max_x)))
        y = max(min_y, min(int(y), int(max_y)))
        return x, y

    def _emit_hover(value):
        if not evt_q:
            return
        try:
            evt_q.put_nowait({"type": "HOVER", "value": value})
        except Exception:
            pass

    class MenuWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()

            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint
                | QtCore.Qt.Tool
                | QtCore.Qt.WindowStaysOnTopHint
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

            self.resize(MENU_SIZE, MENU_SIZE)

            self._active = False
            self._opacity = 0.90

            self._mode = "DEFAULT"
            self._accent = MODE_ACCENT["DEFAULT"]

            self._center_global = None  # logical coords
            self._phase = 0.0

            # hover stability
            self._hover = None
            self._cand = None
            self._cand_since = 0.0
            self._last_nonnull = None
            self._last_nonnull_t = 0.0
            self._last_emit = object()

            # deterministic noise dots (no random import)
            self._dots = []
            for i in range(120):
                a = (i * 37.0) % 360.0
                rr = (OUTER_R * 0.18) + ((i * 53) % int(OUTER_R * 0.74))
                self._dots.append((a, rr, 0.7 + (i % 5) * 0.35))

        def setOpacity(self, v: float):
            self._opacity = float(_clamp(v, 0.20, 0.98))

        def setMode(self, m: str):
            m = str(m or "DEFAULT").upper()
            self._mode = m
            self._accent = MODE_ACCENT.get(m, MODE_ACCENT["DEFAULT"])

        def setActive(self, on: bool):
            on = bool(on)
            if on and (not self._active):
                if self._center_global is None:
                    cur = QCursor.pos()
                    self._center_global = (int(cur.x()), int(cur.y()))
                self._move_to_center()
                self._reset_hover()
                self.show()
            elif (not on) and self._active:
                self.hide()
                self._center_global = None
                self._reset_hover()
                self._emit(None)
            self._active = on

        def setCenter(self, x: int, y: int):
            self._center_global = (int(x), int(y))
            if self._active:
                self._move_to_center()

        def _move_to_center(self):
            if not self._center_global:
                return
            cx, cy = self._center_global
            x = cx - (MENU_SIZE // 2)
            y = cy - (MENU_SIZE // 2)
            x, y = clamp_window(x, y, MENU_SIZE, MENU_SIZE)
            self.move(x, y)

        def _reset_hover(self):
            self._hover = None
            self._cand = None
            self._cand_since = 0.0
            self._last_nonnull = None
            self._last_nonnull_t = 0.0
            self._last_emit = object()

        def _emit(self, value):
            if value == self._last_emit:
                return
            self._last_emit = value
            _emit_hover(value)
            if DEBUG:
                print("[MENU] hover =", value, flush=True)

        def _calc_hover_raw(self):
            if not self._active or not self._center_global:
                return None

            cur = QCursor.pos()
            cx, cy = self._center_global
            dx = float(cur.x() - cx)
            dy = float(cur.y() - cy)
            r = math.hypot(dx, dy)

            if r < DEADZONE_R:
                return None
            if r > HOVER_MAX_R:
                return None

            ang = math.degrees(math.atan2(dy, dx))  # -180..180
            a = _wrap360(ang - START_ANG)
            idx = int(a // STEP) % N
            return ITEMS[idx]

        def tick(self, dt: float):
            self._phase += float(dt)
            now = time.time()

            raw = self._calc_hover_raw()

            if raw is not None:
                self._last_nonnull = raw
                self._last_nonnull_t = now

            # HOLD last non-null for pinch timing
            if raw is None and self._last_nonnull is not None:
                if (now - self._last_nonnull_t) <= HOLD_SECONDS:
                    raw = self._last_nonnull

            # debounce
            if raw != self._cand:
                self._cand = raw
                self._cand_since = now
            else:
                if (now - self._cand_since) >= DEBOUNCE_SECONDS:
                    if raw != self._hover:
                        self._hover = raw
                        self._emit(raw)

            self.update()

        # ---------- paint helpers ----------
        def _arc_path(self, rect, start_deg, span_deg):
            path = QtGui.QPainterPath()
            path.arcMoveTo(rect, start_deg)
            path.arcTo(rect, start_deg, span_deg)
            return path

        def _clip_circle(self, p, cx, cy, r):
            clip = QtGui.QPainterPath()
            clip.addEllipse(QtCore.QPointF(cx, cy), r, r)
            p.setClipPath(clip)

        def _draw_prism_glass(self, p, cx, cy, r):
            # outer glow haze
            haze = QtGui.QRadialGradient(QtCore.QPointF(cx, cy), r + 42)
            haze.setColorAt(0.0, QtGui.QColor(255, 255, 255, 10))
            haze.setColorAt(0.35, QtGui.QColor(80, 200, 255, 18))
            haze.setColorAt(0.75, QtGui.QColor(0, 0, 0, 0))
            haze.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(haze)
            p.drawEllipse(QtCore.QPointF(cx, cy), r + 30, r + 30)

            # body
            body = QtGui.QRadialGradient(QtCore.QPointF(cx, cy), r)
            body.setColorAt(0.0, COL_BG_A)
            body.setColorAt(0.55, QtGui.QColor(9, 14, 20, 150))
            body.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtGui.QPen(COL_EDGE, 1.1))
            p.setBrush(body)
            p.drawEllipse(QtCore.QPointF(cx, cy), r, r)

            # prism edge (two-tone rim)
            rim1 = QtGui.QPen(QtGui.QColor(180, 230, 255, 85), 2.0)
            rim2 = QtGui.QPen(QtGui.QColor(70, 150, 220, 65), 1.0)
            p.setPen(rim1)
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QPointF(cx, cy), r - 6, r - 6)
            p.setPen(rim2)
            p.drawEllipse(QtCore.QPointF(cx, cy), r - 12, r - 12)

        def _draw_grid_scan_noise(self, p, cx, cy, r, w, h, accent):
            p.save()
            self._clip_circle(p, cx, cy, r)

            # micro grid
            step = 18
            ox = int((math.sin(self._phase * 0.65) + 1.0) * 0.5 * step)
            oy = int((math.cos(self._phase * 0.58) + 1.0) * 0.5 * step)
            p.setPen(QtGui.QPen(QtGui.QColor(190, 230, 255, 14), 1))
            for x in range(ox, int(w), step):
                p.drawLine(x, 0, x, int(h))
            for y in range(oy, int(h), step):
                p.drawLine(0, y, int(w), y)

            # scanlines
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 9), 1))
            y = 0
            while y < h:
                p.drawLine(0, y, w, y)
                y += 7

            # noise dots (deterministic)
            p.setPen(QtCore.Qt.NoPen)
            for (a_deg, rr, sz) in self._dots:
                ang = math.radians(a_deg + self._phase * 18.0)
                px = cx + math.cos(ang) * rr
                py = cy + math.sin(ang) * rr
                aa = 18 + int((math.sin(self._phase * 1.2 + rr * 0.02) + 1.0) * 0.5 * 22)
                p.setBrush(QtGui.QColor(accent.red(), accent.green(), accent.blue(), aa))
                p.drawEllipse(QtCore.QPointF(px, py), sz, sz)

            # radar sweep band
            sweep_ang = (self._phase * 42.0) % 360.0
            rect = QtCore.QRectF(cx - r, cy - r, 2 * r, 2 * r)
            band = 22.0
            for k in range(10, 0, -1):
                a = 5 + k * 3
                pen = QtGui.QPen(QtGui.QColor(accent.red(), accent.green(), accent.blue(), a), 1.2 + k * 0.8)
                pen.setCapStyle(QtCore.Qt.FlatCap)
                p.setPen(pen)
                p.drawPath(self._arc_path(rect, -(START_ANG + sweep_ang), -(band)))

            p.restore()

        def _draw_micro_ticks(self, p, cx, cy, r, accent):
            # ticks
            p.setPen(QtGui.QPen(QtGui.QColor(190, 230, 255, 58), 1))
            for i in range(72):
                ang = math.radians(START_ANG + i * 5.0)
                inner = r - (10 if (i % 6) else 20)
                outer = r + 2
                x1 = cx + math.cos(ang) * inner
                y1 = cy + math.sin(ang) * inner
                x2 = cx + math.cos(ang) * outer
                y2 = cy + math.sin(ang) * outer
                p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))

            # crosshair accents
            p.setPen(QtGui.QPen(QtGui.QColor(accent.red(), accent.green(), accent.blue(), 90), 1))
            p.drawLine(int(cx), int(cy - r + 30), int(cx), int(cy - r + 78))
            p.drawLine(int(cx), int(cy + r - 78), int(cx), int(cy + r - 30))
            p.drawLine(int(cx - r + 30), int(cy), int(cx - r + 78), int(cy))
            p.drawLine(int(cx + r - 78), int(cy), int(cx + r - 30), int(cy))

        def _draw_segment_arcs(self, p, cx, cy, r, accent):
            rect = QtCore.QRectF(cx - r, cy - r, 2 * r, 2 * r)

            # base arcs
            base_pen = QtGui.QPen(QtGui.QColor(155, 205, 245, 85), ARC_THICK)
            base_pen.setCapStyle(QtCore.Qt.FlatCap)
            p.setPen(base_pen)
            p.setBrush(QtCore.Qt.NoBrush)

            for i in range(N):
                a0 = START_ANG + i * STEP + ARC_GAP_DEG * 0.5
                span = STEP - ARC_GAP_DEG
                p.drawPath(self._arc_path(rect, -a0, -span))

            # hover glow stack
            hv = self._hover
            if hv:
                try:
                    idx = ITEMS.index(hv)
                    a0 = START_ANG + idx * STEP + ARC_GAP_DEG * 0.5
                    span = STEP - ARC_GAP_DEG

                    for k in range(7, 0, -1):
                        g = QtGui.QColor(accent)
                        g.setAlpha(int(10 + k * 14))
                        pen = QtGui.QPen(g, ARC_THICK + k * 3.4)
                        pen.setCapStyle(QtCore.Qt.FlatCap)
                        p.setPen(pen)
                        p.drawPath(self._arc_path(rect, -a0, -span))

                    crisp = QtGui.QColor(accent)
                    crisp.setAlpha(255)
                    pen2 = QtGui.QPen(crisp, ARC_THICK + 2.2)
                    pen2.setCapStyle(QtCore.Qt.FlatCap)
                    p.setPen(pen2)
                    p.drawPath(self._arc_path(rect, -a0, -span))
                except Exception:
                    pass

        def _draw_labels(self, p, cx, cy, accent):
            hv = self._hover

            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            for i, name in enumerate(ITEMS):
                mid = math.radians(START_ANG + (i + 0.5) * STEP)
                lx = cx + math.cos(mid) * LABEL_R
                ly = cy + math.sin(mid) * LABEL_R

                rect = QtCore.QRectF(lx - LABEL_W * 0.5, ly - LABEL_H * 0.5, LABEL_W, LABEL_H)
                is_h = (name == hv)

                if is_h:
                    bg = QtGui.QColor(accent.red(), accent.green(), accent.blue(), 26)
                    bd = QtGui.QColor(accent.red(), accent.green(), accent.blue(), 210)
                    tx = QtGui.QColor(240, 250, 255, 255)
                else:
                    bg = QtGui.QColor(8, 12, 18, 120)
                    bd = QtGui.QColor(130, 170, 210, 78)
                    tx = QtGui.QColor(225, 245, 255, 215)

                # shadow-ish (offset)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor(0, 0, 0, 90))
                p.drawRoundedRect(rect.translated(2.0, 2.0), 10, 10)

                p.setPen(QtGui.QPen(bd, 1))
                p.setBrush(bg)
                p.drawRoundedRect(rect, 10, 10)

                p.setPen(tx)
                p.drawText(rect, QtCore.Qt.AlignCenter, name)

        def _draw_core(self, p, cx, cy, accent):
            # core rings
            p.setPen(QtGui.QPen(QtGui.QColor(180, 230, 255, 70), 1))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QPointF(cx, cy), OUTER_R - 108, OUTER_R - 108)

            p.setPen(QtGui.QPen(QtGui.QColor(accent.red(), accent.green(), accent.blue(), 95), 2))
            p.drawEllipse(QtCore.QPointF(cx, cy), OUTER_R - 134, OUTER_R - 134)

            # central glow orb
            orb = QtGui.QRadialGradient(QtCore.QPointF(cx, cy), OUTER_R - 150)
            orb.setColorAt(0.0, QtGui.QColor(accent.red(), accent.green(), accent.blue(), 32))
            orb.setColorAt(0.7, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(orb)
            p.drawEllipse(QtCore.QPointF(cx, cy), OUTER_R - 154, OUTER_R - 154)

            # texts
            hv = self._hover or "-"
            p.setPen(COL_TEXT)
            p.setFont(QtGui.QFont("Segoe UI", 18, QtGui.QFont.Bold))
            p.drawText(QtCore.QRectF(cx - 170, cy - 52, 340, 34), QtCore.Qt.AlignCenter, "MODE")

            p.setPen(QtGui.QColor(accent.red(), accent.green(), accent.blue(), 238))
            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            p.drawText(QtCore.QRectF(cx - 170, cy - 16, 340, 22), QtCore.Qt.AlignCenter, f"SELECT : {hv}")

            p.setPen(COL_SUBT)
            p.setFont(QtGui.QFont("Segoe UI", 10))
            p.drawText(QtCore.QRectF(cx - 220, cy + 12, 440, 26),
                       QtCore.Qt.AlignCenter, "PINCH = 확정    FIST = 취소")

        def paintEvent(self, _ev):
            if not self._active:
                return

            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
            p.setOpacity(self._opacity)

            w = self.width()
            h = self.height()
            cx = w * 0.5
            cy = h * 0.5

            ar, ag, ab = _hex_to_rgb(self._accent)
            accent = QtGui.QColor(ar, ag, ab, 255)

            # prism glass disc
            self._draw_prism_glass(p, cx, cy, OUTER_R)

            # inner visuals
            self._draw_grid_scan_noise(p, cx, cy, OUTER_R, w, h, accent)

            # micro ticks + arcs
            self._draw_micro_ticks(p, cx, cy, OUTER_R - 6, accent)
            self._draw_segment_arcs(p, cx, cy, ARC_R, accent)

            # labels + core
            self._draw_labels(p, cx, cy, accent)
            self._draw_core(p, cx, cy, accent)

            p.end()

    app = QtWidgets.QApplication([])
    win = MenuWindow()
    win.hide()

    try:
        _apply_win_exstyle(int(win.winId()), click_through=True)
    except Exception:
        pass

    last_t = time.time()
    timer = QtCore.QTimer()
    timer.setInterval(16)

    def pump_cmd():
        nonlocal last_t

        # handle commands
        while True:
            try:
                msg = cmd_q.get_nowait()
            except Exception:
                break

            if not isinstance(msg, dict):
                continue

            typ = str(msg.get("type", "")).upper()
            if typ == "QUIT":
                app.quit()
                return

            if typ == "ACTIVE":
                win.setActive(bool(msg.get("value", False)))
            elif typ == "MODE":
                win.setMode(msg.get("value", "DEFAULT"))
            elif typ == "OPACITY":
                win.setOpacity(float(msg.get("value", 0.90)))
            elif typ == "CENTER":
                try:
                    win.setCenter(int(msg.get("x")), int(msg.get("y")))
                except Exception:
                    pass

        nowt = time.time()
        dt = max(1e-6, nowt - last_t)
        last_t = nowt
        win.tick(dt)

        # re-apply exstyle sometimes (OS가 가끔 날림)
        if int(nowt * 10) % 60 == 0:
            try:
                _apply_win_exstyle(int(win.winId()), click_through=True)
            except Exception:
                pass

    timer.timeout.connect(pump_cmd)
    timer.start()

    try:
        app.exec()
    except Exception:
        pass
