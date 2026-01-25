# gestureos_agent/qt_menu_overlay.py
# Separate process: radial MODE menu overlay (click-through, topmost, no-activate)
# - Uses Qt logical coords (QCursor.pos, QGuiApplication.screens) to avoid DPI mismatch
# - Center is FIXED when menu opens (cursor position at activation time)
# - Emits evt_q: {"type":"HOVER","value": "<MODE or None>"}
#
# Redesign:
# - Manager UI-like: dark glass, thin grid, segmented neon ring, minimal labels
# - More stable hover: smoothing + debounce to reduce "모드 변경 안됨" 체감

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


def run_menu_process(cmd_q, evt_q):
    if os.name != "nt":
        return

    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtGui import QCursor, QGuiApplication
    except Exception:
        return

    # ---------- config (look & feel) ----------
    MENU_SIZE = 640
    OUTER_R = MENU_SIZE * 0.47
    RING_THICK = 18
    GAP_DEG = 7.0

    # hover valid donut
    INNER_R = OUTER_R - 86
    HOVER_MIN_R = INNER_R + 10
    HOVER_MAX_R = OUTER_R - 14

    LABEL_R = OUTER_R - 44
    CENTER_R = 156

    # Modes (manager와 동일)
    ITEMS = ["PRESENTATION", "MOUSE", "KEYBOARD", "VKEY", "DRAW"]
    N = len(ITEMS)

    START_ANG = -90.0
    STEP = 360.0 / N

    MODE_ACCENT = {
        "MOUSE": "#00ffa6",
        "DRAW": "#ffb020",
        "PRESENTATION": "#3aa0ff",
        "KEYBOARD": "#b26bff",
        "VKEY": "#39ff9a",
        "DEFAULT": "#00ffa6",
    }

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

    def _norm_deg(deg: float) -> float:
        d = deg % 360.0
        return d + 360.0 if d < 0 else d

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
            self._opacity = 0.88

            self._mode = "DEFAULT"
            self._accent = MODE_ACCENT["DEFAULT"]

            self._center_global = None  # (x,y) logical global
            self._phase = 0.0

            # hover stability
            self._hover_raw = None
            self._hover_stable = None
            self._hover_candidate = None
            self._hover_since = 0.0
            self._emit_last = object()

        def setOpacity(self, v: float):
            self._opacity = float(max(0.15, min(0.98, v)))

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
                self._emit_hover(None)
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
            self._hover_raw = None
            self._hover_stable = None
            self._hover_candidate = None
            self._hover_since = 0.0
            self._emit_last = object()

        def _emit_hover(self, value):
            # evt_q: HOVER only
            if value == self._emit_last:
                return
            self._emit_last = value
            if not evt_q:
                return
            try:
                evt_q.put_nowait({"type": "HOVER", "value": value})
            except Exception:
                pass

        def _calc_hover(self):
            if not self._active or not self._center_global:
                return None

            cur = QCursor.pos()
            cx, cy = self._center_global
            dx = float(cur.x() - cx)
            dy = float(cur.y() - cy)

            r = math.hypot(dx, dy)
            if r < HOVER_MIN_R or r > HOVER_MAX_R:
                return None

            ang = math.degrees(math.atan2(dy, dx))  # -180..180 (0:+x)
            # convert to 0..360 where 0 is START_ANG direction
            a = _norm_deg(ang - START_ANG)
            idx = int(a // STEP) % N
            return ITEMS[idx]

        def tick(self, dt: float):
            self._phase += float(dt)

            raw = self._calc_hover()
            self._hover_raw = raw

            # debounce for stability: 80ms
            now = time.time()
            if raw != self._hover_candidate:
                self._hover_candidate = raw
                self._hover_since = now
            else:
                if (now - self._hover_since) >= 0.08:
                    if raw != self._hover_stable:
                        self._hover_stable = raw
                        self._emit_hover(raw)

            self.update()

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

            # -------- background glass + vignette --------
            bg = QtGui.QRadialGradient(QtCore.QPointF(cx, cy), OUTER_R)
            bg.setColorAt(0.0, QtGui.QColor(8, 14, 20, 150))
            bg.setColorAt(0.55, QtGui.QColor(6, 10, 16, 96))
            bg.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(bg)
            p.drawEllipse(QtCore.QPointF(cx, cy), OUTER_R + 6, OUTER_R + 6)

            # subtle grid (manager 느낌)
            p.save()
            clip = QtGui.QPainterPath()
            clip.addEllipse(QtCore.QPointF(cx, cy), OUTER_R + 2, OUTER_R + 2)
            p.setClipPath(clip)
            gridA = 18
            p.setPen(QtGui.QPen(QtGui.QColor(170, 210, 255, gridA), 1))
            step = 18
            ox = int((math.sin(self._phase * 0.7) + 1) * 0.5 * step)
            oy = int((math.cos(self._phase * 0.63) + 1) * 0.5 * step)
            for x in range(0 + ox, int(w), step):
                p.drawLine(x, 0, x, int(h))
            for y in range(0 + oy, int(h), step):
                p.drawLine(0, y, int(w), y)

            # scanlines
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 10), 1))
            y = 0
            while y < h:
                p.drawLine(0, y, w, y)
                y += 7
            p.restore()

            # -------- segmented outer ring --------
            # glow
            for i in range(10, 0, -1):
                g = QtGui.QColor(ar, ag, ab, int(4 + i * 7))
                p.setPen(QtGui.QPen(g, RING_THICK + i * 2.2))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(QtCore.QPointF(cx, cy), OUTER_R - 8, OUTER_R - 8)

            # segments (gapped)
            ring_pen = QtGui.QPen(QtGui.QColor(ar, ag, ab, 220), RING_THICK)
            ring_pen.setCapStyle(QtCore.Qt.FlatCap)
            p.setPen(ring_pen)

            rect = QtCore.QRectF(
                cx - (OUTER_R - 8),
                cy - (OUTER_R - 8),
                (OUTER_R - 8) * 2,
                (OUTER_R - 8) * 2,
            )

            for i in range(N):
                a0 = START_ANG + i * STEP + GAP_DEG * 0.5
                span = STEP - GAP_DEG
                # Qt: arc uses degrees counterclockwise from 3 o'clock, but drawArc in Qt uses 1/16 degrees and CCW
                # We'll use QPainterPath arcTo with negative span to match screen orientation.
                path = QtGui.QPainterPath()
                path.arcMoveTo(rect, -a0)
                path.arcTo(rect, -a0, -span)
                p.drawPath(path)

            # -------- hover highlight --------
            hv = self._hover_stable
            if hv:
                try:
                    idx = ITEMS.index(hv)
                    a0 = START_ANG + idx * STEP + GAP_DEG * 0.5
                    span = STEP - GAP_DEG

                    # wedge fill
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(QtGui.QColor(ar, ag, ab, 26))
                    wedge = QtGui.QPainterPath()
                    wedge.moveTo(cx, cy)
                    wedge.arcTo(rect, -a0, -span)
                    wedge.closeSubpath()
                    p.drawPath(wedge)

                    # stronger segment stroke
                    p.setPen(QtGui.QPen(QtGui.QColor(ar, ag, ab, 255), RING_THICK + 4))
                    path = QtGui.QPainterPath()
                    path.arcMoveTo(rect, -a0)
                    path.arcTo(rect, -a0, -span)
                    p.drawPath(path)
                except Exception:
                    pass

            # -------- inner rings / crosshair --------
            p.setPen(QtGui.QPen(QtGui.QColor(170, 210, 255, 70), 1))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QPointF(cx, cy), INNER_R, INNER_R)
            p.setPen(QtGui.QPen(QtGui.QColor(ar, ag, ab, 110), 2))
            p.drawEllipse(QtCore.QPointF(cx, cy), INNER_R - 28, INNER_R - 28)

            p.setPen(QtGui.QPen(QtGui.QColor(170, 210, 255, 60), 1))
            p.drawLine(int(cx), int(cy - OUTER_R + 24), int(cx), int(cy + OUTER_R - 24))
            p.drawLine(int(cx - OUTER_R + 24), int(cy), int(cx + OUTER_R - 24), int(cy))

            # -------- labels (thin chip style) --------
            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            for i, name in enumerate(ITEMS):
                mid = math.radians(START_ANG + (i + 0.5) * STEP)
                lx = cx + math.cos(mid) * LABEL_R
                ly = cy + math.sin(mid) * LABEL_R

                tw = 160
                th = 30
                rchip = QtCore.QRectF(lx - tw * 0.5, ly - th * 0.5, tw, th)

                is_hover = (name == hv)
                # chip bg/border
                if is_hover:
                    bgc = QtGui.QColor(ar, ag, ab, 36)
                    bdc = QtGui.QColor(ar, ag, ab, 190)
                    txc = QtGui.QColor(235, 248, 255, 255)
                else:
                    bgc = QtGui.QColor(6, 12, 18, 110)
                    bdc = QtGui.QColor(120, 160, 200, 90)
                    txc = QtGui.QColor(220, 240, 255, 210)

                p.setPen(QtGui.QPen(bdc, 1))
                p.setBrush(bgc)
                p.drawRoundedRect(rchip, 10, 10)

                p.setPen(txc)
                p.drawText(rchip, QtCore.Qt.AlignCenter, name)

            # -------- center text --------
            p.setPen(QtGui.QColor(230, 245, 255, 245))
            p.setFont(QtGui.QFont("Segoe UI", 18, QtGui.QFont.Bold))
            p.drawText(
                QtCore.QRectF(cx - CENTER_R, cy - 44, CENTER_R * 2, 34),
                QtCore.Qt.AlignCenter,
                "MODE",
            )

            # selected line
            sel = hv or "-"
            p.setPen(QtGui.QColor(ar, ag, ab, 235))
            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            p.drawText(
                QtCore.QRectF(cx - CENTER_R, cy - 10, CENTER_R * 2, 24),
                QtCore.Qt.AlignCenter,
                f"SELECT : {sel}",
            )

            # hint
            p.setPen(QtGui.QColor(210, 235, 255, 220))
            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Normal))
            p.drawText(
                QtCore.QRectF(cx - CENTER_R, cy + 18, CENTER_R * 2, 28),
                QtCore.Qt.AlignCenter,
                "PINCH = 확정    FIST = 취소",
            )

            p.end()

    app = QtWidgets.QApplication([])
    win = MenuWindow()
    win.hide()

    # apply click-through exstyle
    try:
        _apply_win_exstyle(int(win.winId()), click_through=True)
    except Exception:
        pass

    last_t = time.time()

    timer = QtCore.QTimer()
    timer.setInterval(16)

    def pump_cmd():
        nonlocal last_t
        # commands
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
                win.setOpacity(float(msg.get("value", 0.88)))
            elif typ == "CENTER":
                try:
                    win.setCenter(int(msg.get("x")), int(msg.get("y")))
                except Exception:
                    pass

        nowt = time.time()
        dt = max(1e-6, nowt - last_t)
        last_t = nowt
        win.tick(dt)

        # periodic re-apply win32 exstyle (OS가 리셋하는 경우 방지)
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
