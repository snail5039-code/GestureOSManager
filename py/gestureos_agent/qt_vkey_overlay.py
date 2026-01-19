# gestureos_agent/qt_vkey_overlay.py
# PySide6 virtual keyboard overlay (click-through), runs in a separate process.
#
# Messages on cmd_q:
#   {"type":"ACTIVE","value":bool}
#   {"type":"POINTER","value":[x01,y01]}
#   {"type":"PINCH","value":bool}        # pinch pressed or not
#   {"type":"ENABLE_INPUT","value":bool} # allow SendInput
#   {"type":"QUIT"}

import os
import sys
import time
import queue as pyqueue
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer, QRect, QPointF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

LOG_PATH = os.path.join(os.getenv("TEMP", "."), "GestureOS_VKEY.log")

# =============================================================================
# Win32 SendInput (키 입력)
# =============================================================================
if os.name == "nt":
    ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    user32 = ctypes.windll.user32

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004

    VK_BACK = 0x08
    VK_RETURN = 0x0D
    VK_SPACE = 0x20
    VK_SHIFT = 0x10
    VK_CONTROL = 0x11
    VK_MENU = 0x12  # ALT

    def _send_vk(vk: int):
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))
        up = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))
        user32.SendInput(2, ctypes.byref((INPUT * 2)(down, up)), ctypes.sizeof(INPUT))

    def _send_unicode_char(ch: str):
        if not ch:
            return
        code = ord(ch[0])
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0))
        up = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))
        user32.SendInput(2, ctypes.byref((INPUT * 2)(down, up)), ctypes.sizeof(INPUT))

    def _press_down(vk: int):
        down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=0, time=0, dwExtraInfo=0))
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))

    def _press_up(vk: int):
        up = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

else:
    def _send_vk(vk: int):
        return

    def _send_unicode_char(ch: str):
        return

    def _press_down(vk: int):
        return

    def _press_up(vk: int):
        return


def _desktop_union_rect():
    rect = QRect()
    for s in QGuiApplication.screens():
        g = s.geometry()
        rect = rect.united(g) if not rect.isNull() else QRect(g)
    if rect.isNull():
        rect = QRect(0, 0, 1920, 1080)
    return rect


def _qcolor(hex_, a=1.0):
    h = str(hex_).lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    c = QColor(r, g, b)
    c.setAlphaF(max(0.0, min(1.0, float(a))))
    return c


class VKeyOverlay(QWidget):
    """Virtual keyboard overlay.

    - Completely click-through (mouse transparent)
    - Driven by cmd_q from the main agent
    """

    def __init__(self, cmd_q, evt_q=None):
        super().__init__(None)
        self.cmd_q = cmd_q
        self.evt_q = evt_q

        self.desktop = _desktop_union_rect()
        self.setGeometry(self.desktop)

        flags = (
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        if hasattr(Qt, "WindowTransparentForInput"):
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.active = False
        self.pointer01 = None  # (x01,y01)
        self.pinch = False
        self.enable_input = True

        # one-shot modifiers (next key only)
        self.shift_next = False
        self.ctrl_next = False
        self.alt_next = False

        # keyboard layout
        self.rows = [
            list("QWERTYUIOP"),
            list("ASDFGHJKL"),
            list("ZXCVBNM"),
        ]

        # pinch state
        self._last_pinch = False
        self._pinch_start_ts = None
        self._last_fire_ts = 0.0
        self.PINCH_HOLD_SEC = 0.12
        self.CLICK_COOLDOWN_SEC = 0.25

        self._cached_keys = []  # list[(QRect,label)] in widget coordinates

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ---------- layout ----------
    def _compute_keys(self):
        W = self.desktop.width()
        H = self.desktop.height()

        panel_h = int(H * 0.32)
        panel_y = H - panel_h - 18
        panel_rect = QRect(24, panel_y, W - 48, panel_h)

        margin = 22
        gap = 12
        usable = QRect(panel_rect)
        usable.adjust(margin, margin, -margin, -margin)

        row_h = int((usable.height() - gap * 3) / 4)
        key_h = row_h

        keys = []

        # row 1
        y = usable.top()
        cols = len(self.rows[0])
        key_w = int((usable.width() - gap * (cols - 1)) / cols)
        x = usable.left()
        for ch in self.rows[0]:
            keys.append((QRect(x, y, key_w, key_h), ch))
            x += key_w + gap

        # row 2
        y += key_h + gap
        cols = len(self.rows[1])
        key_w2 = int((usable.width() - gap * (cols - 1)) / cols)
        x = usable.left() + int(key_w2 * 0.35)
        for ch in self.rows[1]:
            keys.append((QRect(x, y, key_w2, key_h), ch))
            x += key_w2 + gap

        # row 3
        y += key_h + gap
        left_w = int(key_w2 * 1.4)
        right_w = int(key_w2 * 1.8)
        mid_cols = len(self.rows[2])
        mid_w = int((usable.width() - left_w - right_w - gap * (mid_cols + 1)) / mid_cols)

        x = usable.left()
        keys.append((QRect(x, y, left_w, key_h), "SHIFT"))
        x += left_w + gap
        for ch in self.rows[2]:
            keys.append((QRect(x, y, mid_w, key_h), ch))
            x += mid_w + gap
        keys.append((QRect(x, y, right_w, key_h), "BKSP"))

        # space row
        y += key_h + gap
        x = usable.left()
        small = int(key_w2 * 1.4)
        keys.append((QRect(x, y, small, key_h), "CTRL"))
        x += small + gap
        keys.append((QRect(x, y, small, key_h), "ALT"))
        x += small + gap

        space_w = usable.right() - x - gap - int(key_w2 * 2.0)
        keys.append((QRect(x, y, space_w, key_h), "SPACE"))
        x += space_w + gap

        enter_w = int(key_w2 * 2.0)
        keys.append((QRect(x, y, enter_w, key_h), "ENTER"))

        return panel_rect, keys

    # ---------- cmd processing ----------
    def _drain(self):
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
                self.active = bool(msg.get("value", False))
                if self.active:
                    self.show()
                    self.raise_()
                else:
                    self.hide()

            elif t == "POINTER":
                v = msg.get("value")
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    try:
                        self.pointer01 = (float(v[0]), float(v[1]))
                    except Exception:
                        pass

            elif t == "PINCH":
                self.pinch = bool(msg.get("value", False))

            elif t == "ENABLE_INPUT":
                self.enable_input = bool(msg.get("value", True))
                if not self.enable_input:
                    # clear one-shot modifiers when disabled
                    self.shift_next = False
                    self.ctrl_next = False
                    self.alt_next = False
                    # also reset pinch timers
                    self._pinch_start_ts = None

            elif t == "QUIT":
                QApplication.instance().quit()
                return

    def _tick(self):
        self._drain()
        if not self.active:
            return

        # cache layout for hit test
        _panel, keys = self._compute_keys()
        self._cached_keys = keys

        # ✅ PINCH hold-to-click (안정화)
        now_ts = time.time()

        if self.enable_input and self.pinch:
            if self._pinch_start_ts is None:
                self._pinch_start_ts = now_ts

            held = now_ts - self._pinch_start_ts
            cooled = (now_ts - self._last_fire_ts) >= self.CLICK_COOLDOWN_SEC

            if held >= self.PINCH_HOLD_SEC and cooled:
                self._fire_under_pointer()
                self._last_fire_ts = now_ts
                self._pinch_start_ts = None  # 다음 클릭을 위해 리셋
        else:
            self._pinch_start_ts = None

        self._last_pinch = self.pinch
        self.update()

    # ---------- pointer helpers ----------
    def _pointer_xy(self):
        if self.pointer01 is None:
            return None
        x01, y01 = self.pointer01
        x01 = max(0.0, min(1.0, x01))
        y01 = max(0.0, min(1.0, y01))
        x = int(self.desktop.left() + x01 * self.desktop.width())
        y = int(self.desktop.top() + y01 * self.desktop.height())
        return x, y

    def _hit_test(self, lx: float, ly: float):
        for r, label in self._cached_keys:
            if r.contains(int(lx), int(ly)):
                return label
        return None

    # ---------- key injection ----------
    def _fire_under_pointer(self):
        pt = self._pointer_xy()
        if pt is None:
            return
        px, py = pt
        lx = px - self.desktop.left()
        ly = py - self.desktop.top()

        label = self._hit_test(lx, ly)
        if not label:
            return

        # one-shot modifier toggles
        if label == "SHIFT":
            self.shift_next = not self.shift_next
            return
        if label == "CTRL":
            self.ctrl_next = not self.ctrl_next
            return
        if label == "ALT":
            self.alt_next = not self.alt_next
            return

        # apply modifiers (down) for THIS key only
        mod_down = []
        if os.name == "nt":
            if self.ctrl_next:
                _press_down(VK_CONTROL)
                mod_down.append(VK_CONTROL)
            if self.alt_next:
                _press_down(VK_MENU)
                mod_down.append(VK_MENU)
            if self.shift_next:
                _press_down(VK_SHIFT)
                mod_down.append(VK_SHIFT)

        try:
            if label == "BKSP":
                if os.name == "nt":
                    _send_vk(VK_BACK)
            elif label == "ENTER":
                if os.name == "nt":
                    _send_vk(VK_RETURN)
            elif label == "SPACE":
                if os.name == "nt":
                    _send_vk(VK_SPACE)
            else:
                # letters
                ch = str(label)[0]
                if not self.shift_next:
                    ch = ch.lower()
                _send_unicode_char(ch)

        finally:
            # release modifiers
            if os.name == "nt":
                for vk in reversed(mod_down):
                    _press_up(vk)

            # clear one-shot latches AFTER a real key
            self.shift_next = False
            self.ctrl_next = False
            self.alt_next = False

    # ---------- painting ----------
    def paintEvent(self, _ev):
        if not self.active:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        panel_rect, keys = self._compute_keys()

        # background panel
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor("#111827", 0.55))
        p.drawRoundedRect(panel_rect, 18, 18)

        p.setPen(QPen(_qcolor("#E5E7EB", 0.35), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(panel_rect, 18, 18)

        font = QFont("Segoe UI", 14, QFont.Bold)
        p.setFont(font)

        def draw_key(r: QRect, label: str, hot: bool = False):
            p.setPen(QPen(_qcolor("#E5E7EB", 0.25), 2))
            if hot:
                p.setBrush(_qcolor("#FFFFFF", 0.20))
            else:
                p.setBrush(_qcolor("#9CA3AF", 0.22))
            p.drawRoundedRect(r, 10, 10)

            # latched indicator
            if label == "SHIFT" and self.shift_next:
                p.setPen(_qcolor("#00E5FF", 0.95))
            elif label == "CTRL" and self.ctrl_next:
                p.setPen(_qcolor("#00E5FF", 0.95))
            elif label == "ALT" and self.alt_next:
                p.setPen(_qcolor("#00E5FF", 0.95))
            else:
                p.setPen(_qcolor("#F9FAFB", 0.92))
            p.drawText(r, Qt.AlignCenter, label)

        # hover key
        hot_label = None
        pt = self._pointer_xy()
        if pt is not None:
            px, py = pt
            lx = px - self.desktop.left()
            ly = py - self.desktop.top()
            hot_label = self._hit_test(lx, ly)

        for r, label in keys:
            draw_key(r, label, hot=(label == hot_label))

        # pointer reticle
        if pt is not None:
            px, py = pt
            lx = px - self.desktop.left()
            ly = py - self.desktop.top()

            p.setPen(QPen(_qcolor("#00E5FF", 0.85), 3))
            p.setBrush(_qcolor("#00E5FF", 0.25))
            p.drawEllipse(QPointF(lx, ly), 16, 16)

            p.setPen(QPen(_qcolor("#FFFFFF", 0.9), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(lx, ly), 6, 6)


def run_vkey_process(cmd_q, evt_q):
    app = QApplication(sys.argv)
    w = VKeyOverlay(cmd_q, evt_q)
    w.hide()
    sys.exit(app.exec())
