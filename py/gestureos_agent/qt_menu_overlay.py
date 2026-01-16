# qt_menu_overlay.py
# PySide6 radial menu overlay (click-through), runs in a separate process.
# - Uses Qt cursor pos (logical coords) + desktop union rect to avoid DPI mismatch as much as possible.

import os
import sys
import math
import time
import queue as pyqueue

from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

LOG_PATH = os.path.join(os.getenv("TEMP", "."), "GestureOS_HUD.log")

def _log(*args):
    try:
        s = " ".join(str(x) for x in args)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {s}\n")
    except Exception:
        pass

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def hex_to_qcolor(h, a=1.0):
    h = str(h).lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    c = QColor(r, g, b)
    c.setAlphaF(max(0.0, min(1.0, float(a))))
    return c

def ang_diff_deg(a, b):
    d = (a - b + 180.0) % 360.0 - 180.0
    return d

def desktop_union_rect() -> QRect:
    rect = QRect()
    screens = QGuiApplication.screens()
    for s in screens:
        g = s.geometry()  # Qt logical coords
        rect = rect.united(g) if not rect.isNull() else QRect(g)
    if rect.isNull():
        rect = QRect(0, 0, 1920, 1080)
    return rect


# =============================================================================
# Text visibility helper (필+외곽선)
# =============================================================================
def draw_text_pill(
    p: QPainter,
    rect: QRect,
    text: str,
    font: QFont,
    fg="#FFFFFF",
    fg_a=0.98,
    outline="#000000",
    outline_a=0.80,
    outline_px=3,
    pill_bg="#000000",
    pill_a=0.55,
    radius=10,
    pad_x=10,
    pad_y=6,
    flags=Qt.AlignCenter,
):
    """
    밝은 배경에서도 무조건 읽히게:
    - 둥근 반투명 배경(pill)
    - 텍스트 외곽선(8방향)
    - 텍스트 본문
    """
    if not text:
        return

    p.save()
    p.setFont(font)

    # pill bg
    bg = hex_to_qcolor(pill_bg, pill_a)
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    pill = QRect(rect)
    pill.adjust(-pad_x, -pad_y, pad_x, pad_y)
    p.drawRoundedRect(pill, radius, radius)

    # outline
    pen_o = QPen(hex_to_qcolor(outline, outline_a))
    pen_o.setWidth(outline_px)
    pen_o.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen_o)

    # 8-direction outline offsets
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)]:
        r2 = QRect(rect)
        r2.translate(dx, dy)
        p.drawText(r2, flags, text)

    # main text
    pen_t = QPen(hex_to_qcolor(fg, fg_a))
    pen_t.setWidth(1)
    p.setPen(pen_t)
    p.drawText(rect, flags, text)

    p.restore()


class RadialMenuOverlay(QWidget):
    def __init__(self, cmd_q, evt_q):
        super().__init__(None)
        self.cmd_q = cmd_q
        self.evt_q = evt_q

        # ✅ 위/아래 잘림 해결: 높이 확장
        self.W = 900
        self.H = 620
        self.setFixedSize(self.W, self.H)

        flags = (
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus
        )
        if hasattr(Qt, "WindowTransparentForInput"):
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.setWindowOpacity(0.95)

        self.active = False
        self.center = None          # if None -> follow cursor, CENTER 오면 고정
        self.current_mode = "DEFAULT"
        self.phase = 0.0
        self.hover = None
        self._last_sent_hover = object()
        self._t_last = time.time()

        self.desktop_rect = desktop_union_rect()

        # ✅ 대비 강화
        self.CYAN = "#00f5ff"
        self.TEXT = "#F2FEFF"
        self.THEME = {
            "MOUSE":        {"accent": "#22c55e"},
            "DRAW":         {"accent": "#f59e0b"},
            "PRESENTATION": {"accent": "#60a5fa"},
            "KEYBOARD":     {"accent": "#a78bfa"},
            "DEFAULT":      {"accent": "#22c55e"},
        }

        # geometry
        self.R_OUT = 210
        self.R_IN  = 145
        self.SPAN  = 26

        # sectors (deg): 0=right, 90=up
        self.sectors = {
            "KEYBOARD": 0.0,
            "DRAW": 90.0,
            "MOUSE": 180.0,
            "PPT": 270.0,
        }

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def set_active(self, v: bool):
        self.active = bool(v)
        if self.active:
            self.show()
            self.raise_()
            self.update()
        else:
            self.hide()

    def set_center(self, x, y):
        self.center = (int(x), int(y))

    def set_mode(self, m: str):
        m = str(m or "DEFAULT").upper()
        # PPT는 표시만 PPT
        if m == "PRESENTATION":
            m = "PPT"
        self.current_mode = m if m in self.THEME or m == "PPT" else "DEFAULT"

    def set_opacity(self, o: float):
        try:
            o = float(o)
            o = max(0.20, min(1.0, o))
            self.setWindowOpacity(o)
        except Exception:
            pass

    def hit_test(self, osx, osy):
        if osx is None or osy is None:
            return None

        wx = self.x()
        wy = self.y()
        lx = float(osx - wx)
        ly = float(osy - wy)

        cx = self.W * 0.5
        cy = self.H * 0.5

        dx = lx - cx
        dy = ly - cy
        r = math.hypot(dx, dy)
        if r < self.R_IN or r > self.R_OUT:
            return None

        ang = (math.degrees(math.atan2(-dy, dx)) + 360.0) % 360.0

        best = None
        best_abs = 999.0
        for k, center in self.sectors.items():
            d = abs(ang_diff_deg(ang, center))
            if d <= self.SPAN and d < best_abs:
                best_abs = d
                best = k
        return best

    def drain_commands(self):
        while True:
            try:
                msg = self.cmd_q.get_nowait()
            except pyqueue.Empty:
                break
            except Exception:
                break

            if not isinstance(msg, dict):
                continue

            t = msg.get("type")
            if t == "ACTIVE":
                self.set_active(bool(msg.get("value", False)))
            elif t == "CENTER":
                c = msg.get("value")
                if isinstance(c, (list, tuple)) and len(c) == 2:
                    self.set_center(c[0], c[1])
            elif t == "MODE":
                self.set_mode(msg.get("value", "DEFAULT"))
            elif t == "OPACITY":
                self.set_opacity(msg.get("value", 0.82))
            elif t == "QUIT":
                QApplication.instance().quit()
                return

    def tick(self):
        t = time.time()
        dt = max(1e-6, t - self._t_last)
        self._t_last = t
        self.phase += dt

        self.drain_commands()
        if not self.active:
            return

        cur = QCursor.pos()
        osx, osy = int(cur.x()), int(cur.y())

        if self.center is None:
            cx, cy = osx, osy
        else:
            cx, cy = self.center

        x = int(cx - self.W // 2)
        y = int(cy - self.H // 2)

        r = self.desktop_rect
        min_x = r.left()
        min_y = r.top()
        max_x = r.right() - self.W
        max_y = r.bottom() - self.H

        x = clamp(x, min_x, max_x)
        y = clamp(y, min_y, max_y)
        self.move(QPoint(x, y))

        h = self.hit_test(osx, osy)
        self.hover = h

        if h != self._last_sent_hover:
            self._last_sent_hover = h
            try:
                self.evt_q.put_nowait({"type": "HOVER", "value": h})
            except Exception:
                pass

        self.update()

    def paintEvent(self, _ev):
        if not self.active:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        W, H = self.W, self.H
        cx, cy = W * 0.5, H * 0.5

        cyan = self.CYAN
        cyan_dim = hex_to_qcolor(cyan, 0.95)
        cyan_low = hex_to_qcolor(cyan, 0.65)

        # corner brackets
        def corner(x, y, sx, sy):
            p.setPen(QPen(hex_to_qcolor(cyan, 0.22), 7))
            p.drawLine(x, y, x + 36 * sx, y)
            p.drawLine(x, y, x, y + 36 * sy)
            p.setPen(QPen(hex_to_qcolor(cyan, 0.70), 2))
            p.drawLine(x, y, x + 36 * sx, y)
            p.drawLine(x, y, x, y + 36 * sy)

        pad = 26
        corner(pad, pad, +1, +1)
        corner(W - pad, pad, -1, +1)
        corner(pad, H - pad, +1, -1)
        corner(W - pad, H - pad, -1, -1)

        # dot grid
        p.setPen(Qt.NoPen)
        for yy in range(60, H - 60, 72):
            for xx in range(60, W - 60, 96):
                p.setBrush(hex_to_qcolor(cyan, 0.22))
                p.drawEllipse(QPoint(xx, yy), 1, 1)

        def ring(r_, col, w):
            p.setPen(QPen(col, w))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r_), int(r_))

        ring(self.R_OUT, cyan_dim, 5)
        ring(self.R_IN,  cyan_low, 5)

        # spinning segments
        r_ = self.R_OUT
        for i in range(12):
            start = (i * 30 + self.phase * 46.0) % 360.0
            p.setPen(QPen(cyan_dim, 3))
            p.drawArc(int(cx - r_), int(cy - r_), int(2 * r_), int(2 * r_),
                      int(-start * 16), int(-10 * 16))

        # sweep
        sweep_start = (self.phase * 90.0) % 360.0
        p.setPen(QPen(hex_to_qcolor(cyan, 0.92), 6))
        p.drawArc(int(cx - r_), int(cy - r_), int(2 * r_), int(2 * r_),
                  int(-sweep_start * 16), int(-38 * 16))

        # scan line
        scan_y = 70 + int((self.phase * 120.0) % (H - 140))
        p.setPen(QPen(hex_to_qcolor(cyan, 0.16), 2))
        p.drawLine(90, scan_y, W - 90, scan_y)

        # center title (✅ pill + outline)
        center_title_rect = QRect(int(cx - 160), int(cy - 26), 320, 28)
        draw_text_pill(
            p, center_title_rect, "MODE SELECT",
            font=QFont("Segoe UI", 16, QFont.Bold),
            fg="#FFFFFF", fg_a=0.98,
            outline="#000000", outline_a=0.85, outline_px=3,
            pill_bg="#000000", pill_a=0.45, radius=12
        )

        cm = self.current_mode if self.current_mode else "DEFAULT"
        cm_col = self.THEME.get(cm, self.THEME["DEFAULT"])["accent"] if cm != "PPT" else "#60a5fa"
        center_mode_rect = QRect(int(cx - 160), int(cy + 6), 320, 26)
        draw_text_pill(
            p, center_mode_rect, cm,
            font=QFont("Segoe UI", 14, QFont.Bold),
            fg="#FFFFFF", fg_a=0.98,
            outline="#000000", outline_a=0.85, outline_px=3,
            pill_bg="#000000", pill_a=0.45, radius=12
        )

        # sectors
        r_mid = (self.R_IN + self.R_OUT) * 0.5
        for k, center_deg in self.sectors.items():
            base = cyan_dim
            w = 10

            if k == cm:
                base = hex_to_qcolor(cm_col, 0.75)

            if self.hover == k:
                # hover는 더 강하게
                accent = "#60a5fa" if k == "PPT" else self.THEME.get(k, self.THEME["DEFAULT"])["accent"]
                base = hex_to_qcolor(accent, 0.98)
                w = 14  # ✅ (원래 w=1 이라 거의 안 보였음)

            p.setPen(QPen(base, w))
            start = center_deg - self.SPAN
            extent = self.SPAN * 2
            rr = r_mid
            p.drawArc(int(cx - rr), int(cy - rr), int(2 * rr), int(2 * rr),
                      int(-start * 16), int(-extent * 16))

            rad = math.radians(center_deg)
            bx = int(cx + math.cos(rad) * (self.R_OUT + 46))
            by = int(cy - math.sin(rad) * (self.R_OUT + 46))

            label_kr = {
                "MOUSE": "마우스",
                "KEYBOARD": "키보드",
                "DRAW": "그리기",
                "PPT": "PPT",
            }.get(k, k)

            # ✅ 라벨도 pill + outline (밝은 배경에서 무조건 보임)
            label_rect = QRect(bx - 90, by - 12, 180, 24)

            if self.hover == k:
                accent = "#60a5fa" if k == "PPT" else self.THEME.get(k, self.THEME["DEFAULT"])["accent"]
                draw_text_pill(
                    p, label_rect, label_kr,
                    font=QFont("Segoe UI", 14, QFont.Bold),
                    fg="#FFFFFF", fg_a=0.98,
                    outline="#000000", outline_a=0.90, outline_px=3,
                    pill_bg="#000000", pill_a=0.62, radius=10
                )
            else:
                draw_text_pill(
                    p, label_rect, label_kr,
                    font=QFont("Segoe UI", 14, QFont.Bold),
                    fg="#FFFFFF", fg_a=0.97,
                    outline="#000000", outline_a=0.85, outline_px=3,
                    pill_bg="#000000", pill_a=0.50, radius=10
                )

        # hint (✅ pill + outline)
        hint_rect = QRect(0, H - 34, W, 24)
        draw_text_pill(
            p, hint_rect,
            "양손 V_SIGN 홀드로 열기  •  PINCH=확정  •  FIST=취소",
            font=QFont("Segoe UI", 10, QFont.Bold),
            fg="#FFFFFF", fg_a=0.95,
            outline="#000000", outline_a=0.90, outline_px=3,
            pill_bg="#000000", pill_a=0.55, radius=10, pad_x=12, pad_y=6
        )


def run_menu_process(cmd_q, evt_q):
    try:
        _log("[QT] run_menu_process start")
        app = QApplication(sys.argv)
        w = RadialMenuOverlay(cmd_q, evt_q)
        w.hide()
        _log("[QT] app exec")
        sys.exit(app.exec())
    except Exception as e:
        _log("[QT] crashed:", repr(e))
        raise
