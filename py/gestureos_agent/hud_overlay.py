# gestureos_agent/hud_overlay.py
# Windows only: Always-on-top transparent HUD overlay (click-through)
# PySide6 (Qt) - Clean Cyber/VR HUD redesign
#
# FIXES:
# - Menu hover "latch" (debounce): prevents hover=None at confirm timing.
# - Menu "freeze center at open": menu does not follow cursor while active.
# - Cleaner HUD: less noisy glow/scanlines, better spacing, typography.
# - Robust single-instance + log.
# - Win11: 초기 표시 실패(안 보임) 케이스 대응: HUD/Tip/Handle 3창 show/raise + TOPMOST 재강제 + exstyle 재적용

import os
import time
import math
import atexit
import ctypes
import multiprocessing as mp
import threading
from ctypes import wintypes
from dataclasses import dataclass

HUD_DEBUG = (os.getenv("HUD_DEBUG", "0") == "1")
LOG_PATH = os.path.join(os.getenv("TEMP", "."), "GestureOS_HUD.log")


def _log(*args):
    try:
        s = " ".join(str(x) for x in args)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {s}\n")
    except Exception:
        pass


# ---- try import Qt menu process entry (패키지/루트 둘 다 지원) ----
run_menu_process = None
_import_errs = []
try:
    from gestureos_agent.qt_menu_overlay import run_menu_process as _rmp

    run_menu_process = _rmp
except Exception as e1:
    _import_errs.append(repr(e1))
    try:
        from qt_menu_overlay import run_menu_process as _rmp2

        run_menu_process = _rmp2
    except Exception as e2:
        _import_errs.append(repr(e2))
        run_menu_process = None
        _log("[HUD] qt_menu_overlay import failed:", " / ".join(_import_errs))
        if HUD_DEBUG:
            print("[HUD] qt_menu_overlay import failed:", " / ".join(_import_errs), flush=True)


# ---------------- Win32 constants ----------------
GWL_EXSTYLE = -20

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

ERROR_ALREADY_EXISTS = 183
HUD_MUTEX_NAME = "Global\\GestureOS_HUD_Overlay_SingleInstance"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


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


THEME = {
    "MOUSE": {"accent": "#00FFA6"},
    "DRAW": {"accent": "#FFB020"},
    "PRESENTATION": {"accent": "#3AA0FF"},
    "KEYBOARD": {"accent": "#B26BFF"},
    "VKEY": {"accent": "#39FF9A"},
    "RUSH_HAND": {"accent": "#FF3D7F"},
    "RUSH_COLOR": {"accent": "#FFD23D"},
    "DEFAULT": {"accent": "#00FFA6"},
}


def _mode_of(status: dict) -> str:
    m = str(status.get("mode", "DEFAULT")).upper()
    return m if m in THEME else "DEFAULT"


def _hex_to_rgb(color_hex: str):
    s = str(color_hex).lstrip("#")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return r, g, b


def _pick_first_str(st: dict, keys):
    for k in keys:
        v = st.get(k, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _common_state_label(st: dict, locked: bool):
    enabled = bool(st.get("enabled", True))
    if not enabled:
        return "비활성"
    if locked:
        return "잠김"
    return None



def _action_mouse(st: dict, locked: bool) -> str:
    # ✅ 상태/바인딩 기반으로 "현재 동작"을 표시 (설정 변경 즉시 반영)
    if not st.get("enabled", False):
        return "비활성"

    if locked:
        return "잠금"

    g = str(st.get("gesture", "NONE") or "NONE").upper()
    scroll_active = bool(st.get("scrollActive", False))

    m = st.get("mouseBindings") or {}
    if not isinstance(m, dict):
        m = {}

    move_g = str(m.get("MOVE", "OPEN_PALM") or "OPEN_PALM").upper()
    click_g = str(m.get("CLICK_DRAG", "PINCH_INDEX") or "PINCH_INDEX").upper()
    rc_g = str(m.get("RIGHT_CLICK", "V_SIGN") or "V_SIGN").upper()
    lock_g = str(m.get("LOCK_TOGGLE", "FIST") or "FIST").upper()
    scroll_hold_g = str(m.get("SCROLL_HOLD", "FIST") or "FIST").upper()

    # 우선순위: 스크롤(활성) > 잠금 토글 제스처 > 클릭/우클릭 > 이동
    if scroll_active or (g == scroll_hold_g):
        return "스크롤"

    if g == lock_g:
        return "잠금 토글"

    if g == click_g:
        return "클릭/드래그"

    if g == rc_g:
        return "우클릭"

    if g == move_g:
        return "이동"

    return "대기"

def _action_draw(st: dict, locked: bool) -> str:
    common = _common_state_label(st, locked)
    if common:
        return common
    tool = _pick_first_str(st, ["tool", "drawTool", "brush", "pen", "eraser"])
    if tool:
        return f"{tool}"
    g = str(st.get("gesture", "NONE") or "NONE").upper()
    if g == "PINCH_INDEX":
        return "그리기"
    if g == "OPEN_PALM":
        return "이동"
    if g == "V_SIGN":
        return "도구"
    if g == "FIST":
        return "지우기(홀드)"
    return "대기"



def _action_presentation(st: dict, locked: bool) -> str:
    """PPT/PRESENTATION 모드 액션 라벨(모드 Pill에 표시).

    요구사항(단순 고정):
      - OPEN_PALM: 커서 이동
      - PINCH_INDEX: 클릭(선택)
      - FIST: 다음 슬라이드
      - V_SIGN: 이전 슬라이드
      - (양손) OPEN_PALM+OPEN_PALM: 발표 시작(F5)
      - (양손) FIST+FIST(홀드): 발표 종료(ESC)
      - (양손) PINCH_INDEX+PINCH_INDEX(홀드): ALT+TAB

    HUD는 홀드 시간을 모르므로 '양손 제스처가 들어오면' 라벨을 미리 보여준다.
    실제 키 주입/홀드 디바운스는 hands_agent/presentation handler에서 처리.
    """
    g = str(st.get("gesture", "NONE") or "NONE").upper()
    og = str(st.get("otherGesture", "NONE") or "NONE").upper()

    # global lock 안내 우선
    if locked:
        return "잠금"

    # 양손 제스처(피드백용)
    if g == "OPEN_PALM" and og == "OPEN_PALM":
        return "발표 시작(F5)"
    if g == "FIST" and og == "FIST":
        return "발표 종료(ESC)"
    if g == "PINCH_INDEX" and og == "PINCH_INDEX":
        return "직전 앱(ALT+TAB)"

    # 한손 제스처
    if g == "OPEN_PALM":
        return "커서"
    if g == "PINCH_INDEX":
        return "클릭"
    if g == "FIST":
        return "다음(→)"
    if g == "V_SIGN":
        return "이전(←)"

    return "대기"

    if locked:
        return "잠금"

    g = str(st.get("gesture", "NONE") or "NONE").upper()

    # ✅ hands_agent STATUS의 바인딩(pptNav/pptInteract)을 우선 사용 (설정 변경 즉시 반영)
    nav = st.get("pptNav") or {}
    inter = st.get("pptInteract") or {}
    if not isinstance(nav, dict):
        nav = {}
    if not isinstance(inter, dict):
        inter = {}

    def _match(action_key: str, default_g: str = "") -> bool:
        want = nav.get(action_key)
        if want is None:
            want = inter.get(action_key)
        if want is None and default_g:
            want = default_g
        want = str(want or "").upper()
        return bool(want) and (g == want)

    if _match("NEXT"):
        return "다음"
    if _match("PREV"):
        return "이전"
    if _match("ACTIVATE") or _match("CLICK") or _match("ENTER"):
        return "활성/클릭"
    if _match("TAB"):
        return "TAB"
    if _match("SHIFT_TAB"):
        return "SHIFT+TAB"
    if _match("PLAY_PAUSE"):
        return "재생/일시정지"

    # fallback (기존 하드코딩)
    if g == "OPEN_PALM":
        return "포인터"
    if g == "PINCH_INDEX":
        return "활성/클릭"
    if g == "FIST":
        return "다음"
    if g == "V_SIGN":
        return "이전"

    return "대기"


def _action_keyboard(st: dict, locked: bool) -> str:
    if not st.get("enabled", False):
        return "비활성"
    if locked:
        return "잠금"

    g = str(st.get("gesture", "NONE") or "NONE").upper()
    og = str(st.get("otherGesture", "NONE") or "NONE").upper()

    # 두손 조합(MOUSE_MOD)으로 마우스 게이트가 켜져 있으면 그걸 우선 표기
    if bool(st.get("kbMouseGate", False)):
        mod_g = str(st.get("kbMouseMod", "") or "").upper()
        return f"마우스 게이트({mod_g})" if mod_g else "마우스 게이트"

    base = st.get("kbBase") or {}
    fn = st.get("kbFn") or {}
    if not isinstance(base, dict):
        base = {}
    if not isinstance(fn, dict):
        fn = {}

    fn_hold = str(st.get("kbFnHold", "") or "").upper()
    fn_active = bool(fn_hold) and (og == fn_hold)

    mapping = fn if fn_active else base

    # reverse lookup: 현재 커서 제스처가 어떤 키 액션으로 매핑됐는지
    for key, gest in mapping.items():
        if str(gest or "").upper() == g:
            # key는 LEFT/RIGHT/UP/DOWN/ENTER/SPACE... 등
            return f"{'FN:' if fn_active else ''}{str(key)}"

    return "대기"

def _action_vkey(st: dict, locked: bool) -> str:
    common = _common_state_label(st, locked)
    if common:
        return common
    sel = _pick_first_str(st, ["vk", "vkey", "selectedKey", "key", "keyName", "char"])
    g = str(st.get("gesture", "NONE") or "NONE").upper()
    if g == "PINCH_INDEX":
        return f"입력({sel})" if sel else "입력"
    if g == "OPEN_PALM":
        return "선택"
    if sel:
        return f"선택({sel})"
    return "대기"


def _action_default(st: dict, locked: bool) -> str:
    common = _common_state_label(st, locked)
    if common:
        return common
    g = str(st.get("gesture", "NONE") or "NONE").strip()
    if g and g.upper() != "NONE":
        return g
    return "대기"


def _bubble_text(st: dict, mode: str, locked: bool) -> str:
    mode_u = str(mode).upper()
    bubble = st.get("cursorBubble", None)
    if bubble is not None:
        return str(bubble).strip()

    if mode_u == "MOUSE":
        action = _action_mouse(st, locked)
    elif mode_u == "DRAW":
        action = _action_draw(st, locked)
    elif mode_u == "PRESENTATION":
        action = _action_presentation(st, locked)
    elif mode_u == "KEYBOARD":
        action = _action_keyboard(st, locked)
    elif mode_u == "VKEY":
        action = _action_vkey(st, locked)
    else:
        action = _action_default(st, locked)

    action = str(action).strip() if action is not None else ""
    return f"{mode_u} • {action}" if action else mode_u


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


def _acquire_single_instance():
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.GetLastError.restype = wintypes.DWORD
    kernel32.CloseHandle.restype = wintypes.BOOL

    h = kernel32.CreateMutexW(None, True, HUD_MUTEX_NAME)
    if not h:
        return (True, None)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        try:
            kernel32.CloseHandle(h)
        except Exception:
            pass
        return (False, None)
    return (True, h)


def _release_single_instance(h):
    if h:
        try:
            kernel32.CloseHandle(h)
        except Exception:
            pass


# =========================
# VISUAL TUNING (YOU CAN TWEAK)
# =========================
@dataclass
class _HudGeom:
    HUD_W: int = 360
    HUD_H: int = 150

    HANDLE_W: int = 34
    HANDLE_H: int = 28
    HANDLE_PAD_R: int = 14
    HANDLE_PAD_T: int = 14

    TIP_W_MIN: int = 190
    TIP_W_MAX: int = 640
    TIP_H: int = 46
    TIP_OX: int = 22
    TIP_OY: int = -64

    PAD: int = 10


# =========================
# HUD PROCESS
# =========================
def _hud_process_main(cmd_q: mp.Queue, evt_q: mp.Queue):
    if os.name != "nt":
        return

    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        from PySide6.QtGui import QCursor, QGuiApplication
    except Exception as e:
        _log("[HUD] PySide6 import failed in HUD process:", repr(e))
        return

    ok, mutex_h = _acquire_single_instance()
    if not ok:
        _log("[HUD] single instance already exists -> exit")
        return

    geom = _HudGeom()

    latest = {}
    panel_visible = True

    # menu state
    menu_active = False
    menu_hover = None

    # freeze center at open
    menu_frozen_center = None  # (x,y) logical global
    prev_menu_active = False

    phase = 0.0
    last_t = time.time()

    def desktop_union_rect_qt() -> QtCore.QRect:
        rect = QtCore.QRect()
        for s in QGuiApplication.screens():
            g = s.geometry()
            rect = rect.united(g) if not rect.isNull() else QtCore.QRect(g)
        if rect.isNull():
            rect = QtCore.QRect(0, 0, 1920, 1080)
        return rect

    desktop_rect = None

    def clamp_in_desktop(x, y, w, h):
        nonlocal desktop_rect
        if desktop_rect is None:
            desktop_rect = desktop_union_rect_qt()
        r = desktop_rect
        min_x = r.left()
        min_y = r.top()
        max_x = r.right() - w
        max_y = r.bottom() - h
        x = max(min_x, min(int(x), int(max_x)))
        y = max(min_y, min(int(y), int(max_y)))
        return x, y

    # ---- menu process management ----
    qt_ok = False
    qt_cmd_q = None
    qt_evt_q = None
    qt_proc = None

    qt_last_active = None
    qt_last_center = None
    qt_last_mode = None
    qt_last_opacity = None

    def menu_start():
        nonlocal qt_ok, qt_cmd_q, qt_evt_q, qt_proc
        nonlocal qt_last_active, qt_last_center, qt_last_mode, qt_last_opacity

        if run_menu_process is None:
            qt_ok = False
            _log("[HUD] run_menu_process is None")
            return

        if qt_proc is not None and qt_proc.is_alive():
            qt_ok = True
            return

        try:
            mp.freeze_support()
            qt_cmd_q = mp.Queue()
            qt_evt_q = mp.Queue()
            qt_proc = mp.Process(target=run_menu_process, args=(qt_cmd_q, qt_evt_q), daemon=True)
            qt_proc.start()
            qt_ok = True

            qt_last_active = None
            qt_last_center = None
            qt_last_mode = None
            qt_last_opacity = None
            _log("[HUD] menu process started")
        except Exception as e:
            qt_ok = False
            _log("[HUD] Qt menu start failed:", repr(e))

    def menu_stop():
        nonlocal qt_ok, qt_cmd_q, qt_evt_q, qt_proc
        try:
            if qt_cmd_q:
                try:
                    qt_cmd_q.put({"type": "QUIT"})
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if qt_proc:
                qt_proc.join(timeout=1.0)
        except Exception:
            pass

        qt_proc = None
        qt_cmd_q = None
        qt_evt_q = None
        qt_ok = False
        _log("[HUD] menu process stopped")

    def menu_send(msg: dict):
        if not qt_ok or not qt_cmd_q:
            return
        try:
            qt_cmd_q.put_nowait(msg)
        except Exception:
            pass

    def _evt_forward(payload: dict):
        if not evt_q:
            return
        try:
            evt_q.put_nowait(payload)
        except Exception:
            pass

    def menu_pump_events():
        """
        IMPORTANT:
        - qt_menu_overlay may emit HOVER None intermittently.
        - We forward raw events; main OverlayHUD will latch it.
        """
        nonlocal menu_hover
        if not qt_ok or not qt_evt_q:
            return
        while True:
            try:
                ev = qt_evt_q.get_nowait()
            except Exception:
                break
            if not isinstance(ev, dict):
                continue
            if str(ev.get("type", "")).upper() == "HOVER":
                menu_hover = ev.get("value")
                _evt_forward({"type": "HOVER", "value": menu_hover})

    def menu_sync(active: bool, center_xy, mode: str):
        nonlocal qt_last_active, qt_last_center, qt_last_mode, qt_last_opacity, qt_ok

        if qt_proc is not None and (not qt_proc.is_alive()):
            menu_start()

        if not qt_ok:
            return

        a = bool(active)
        if qt_last_active != a:
            qt_last_active = a
            menu_send({"type": "ACTIVE", "value": a})
            _evt_forward({"type": "MENU_ACTIVE", "value": a})

        m = str(mode or "DEFAULT").upper()
        if qt_last_mode != m:
            qt_last_mode = m
            menu_send({"type": "MODE", "value": m})

        if qt_last_opacity is None:
            qt_last_opacity = 0.90
            menu_send({"type": "OPACITY", "value": 0.90})

        if center_xy is not None:
            try:
                cx, cy = int(center_xy[0]), int(center_xy[1])
                if qt_last_center != (cx, cy):
                    qt_last_center = (cx, cy)
                    menu_send({"type": "CENTER", "x": cx, "y": cy})
            except Exception:
                pass

    # ---- HUD windows ----
    class HudWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.resize(geom.HUD_W, geom.HUD_H)

            self._mode = "DEFAULT"
            self._accent = "#00FFA6"
            self._tracking = False
            self._locked = False
            self._gesture = "NONE"
            self._fps = 0.0
            self._connected = True
            self._phase = 0.0
            self._menu_active = False

        def setState(self, mode, accent, tracking, locked, gesture, fps, connected, phase, menu_active=False):
            self._mode = mode
            self._accent = accent
            self._tracking = bool(tracking)
            self._locked = bool(locked)
            self._gesture = str(gesture)
            self._fps = float(fps or 0.0)
            self._connected = bool(connected)
            self._phase = float(phase or 0.0)
            self._menu_active = bool(menu_active)
            self.update()

        def paintEvent(self, _ev):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

            w = self.width()
            h = self.height()
            accent_r, accent_g, accent_b = _hex_to_rgb(self._accent)

            pad = geom.PAD
            rect = QtCore.QRectF(pad, pad, w - pad * 2, h - pad * 2)

            baseA = 165 if self._tracking else 150
            base = QtGui.QColor(8, 16, 24, baseA)
            base2 = QtGui.QColor(4, 10, 16, baseA - 10)
            grad = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, base)
            grad.setColorAt(1.0, base2)

            glow_alpha = 55 if self._tracking else 40
            for i in range(5, 0, -1):
                g = QtGui.QColor(accent_r, accent_g, accent_b, int(glow_alpha * (i / 5.0)))
                p.setPen(QtGui.QPen(g, 1.0 + i * 0.9))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-i, -i, i, i), 18 + i, 18 + i)

            p.setPen(QtGui.QPen(QtGui.QColor(60, 110, 150, 140), 1.0))
            p.setBrush(QtGui.QBrush(grad))
            p.drawRoundedRect(rect, 18, 18)

            hi = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
            hi.setColorAt(0.0, QtGui.QColor(255, 255, 255, 40))
            hi.setColorAt(0.18, QtGui.QColor(255, 255, 255, 12))
            hi.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(hi)
            p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 17, 17)

            p.setPen(QtGui.QPen(QtGui.QColor(accent_r, accent_g, accent_b, 140), 1.5))
            p.drawLine(
                QtCore.QPointF(rect.left() + 14, rect.top() + 44),
                QtCore.QPointF(rect.right() - 14, rect.top() + 44),
            )

            cx = rect.left() + 20
            cy = rect.top() + 22
            dot = QtGui.QColor(0, 255, 160, 230) if self._connected else QtGui.QColor(255, 90, 90, 230)
            p.setPen(QtGui.QPen(dot, 2))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(QtCore.QPointF(cx, cy), 5.8, 5.8)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QtCore.QPointF(cx, cy), 2.1, 2.1)

            p.setPen(QtGui.QColor(235, 248, 255, 245))
            p.setFont(QtGui.QFont("Segoe UI", 12, QtGui.QFont.Bold))
            p.drawText(QtCore.QPointF(rect.left() + 34, rect.top() + 26), self._mode)

            chip_text = "LOCKED" if self._locked else "ACTIVE"
            chip_bg = QtGui.QColor(255, 178, 32, 195) if self._locked else QtGui.QColor(accent_r, accent_g, accent_b, 70)
            chip_bd = QtGui.QColor(70, 120, 160, 170)

            chip_w, chip_h = 92, 22
            chip_x = rect.right() - 16 - chip_w - (geom.HANDLE_W + 8)
            chip_y = rect.top() + 12
            chip = QtCore.QRectF(chip_x, chip_y, chip_w, chip_h)

            p.setPen(QtGui.QPen(chip_bd, 1))
            p.setBrush(chip_bg)
            p.drawRoundedRect(chip, 11, 11)
            p.setPen(QtGui.QColor(8, 18, 28, 245))
            p.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Bold))
            p.drawText(chip, QtCore.Qt.AlignCenter, chip_text)

            if self._menu_active:
                rr = QtCore.QRectF(chip.left() - 58, chip_y + 2, 50, 18)
                p.setPen(QtGui.QPen(QtGui.QColor(accent_r, accent_g, accent_b, 190), 1))
                p.setBrush(QtGui.QColor(accent_r, accent_g, accent_b, 38))
                p.drawRoundedRect(rr, 9, 9)
                p.setPen(QtGui.QColor(235, 248, 255, 235))
                p.setFont(QtGui.QFont("Segoe UI", 8, QtGui.QFont.Bold))
                p.drawText(rr, QtCore.Qt.AlignCenter, "MENU")

            sub = QtGui.QColor(175, 210, 235, 225)
            p.setPen(sub)
            p.setFont(QtGui.QFont("Segoe UI", 9))

            gtxt = str(self._gesture or "NONE")
            t_on = "ON" if self._tracking else "OFF"
            p.drawText(QtCore.QPointF(rect.left() + 18, rect.top() + 70), f"GESTURE  {gtxt}")
            p.drawText(QtCore.QPointF(rect.left() + 18, rect.top() + 90), f"TRACK    {t_on}")
            p.drawText(QtCore.QPointF(rect.left() + 18, rect.top() + 110), f"FPS      {self._fps:.1f}")

            p.setPen(QtGui.QPen(QtGui.QColor(accent_r, accent_g, accent_b, 160), 2))
            s = 12
            x0, y0 = rect.left() + 10, rect.top() + 10
            x1, y1 = rect.right() - 10, rect.bottom() - 10
            p.drawLine(QtCore.QPointF(x0, y0 + s), QtCore.QPointF(x0, y0))
            p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x0 + s, y0))
            p.drawLine(QtCore.QPointF(x1 - s, y0), QtCore.QPointF(x1, y0))
            p.drawLine(QtCore.QPointF(x1, y0), QtCore.QPointF(x1, y0 + s))
            p.drawLine(QtCore.QPointF(x0, y1 - s), QtCore.QPointF(x0, y1))
            p.drawLine(QtCore.QPointF(x0, y1), QtCore.QPointF(x0 + s, y1))
            p.drawLine(QtCore.QPointF(x1 - s, y1), QtCore.QPointF(x1, y1))
            p.drawLine(QtCore.QPointF(x1, y1 - s), QtCore.QPointF(x1, y1))

            p.end()

    class TipWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.resize(320, geom.TIP_H)
            self._text = ""
            self._accent = "#00FFA6"
            self._phase = 0.0

        def setState(self, text, accent, phase):
            self._text = str(text or "")
            self._accent = accent
            self._phase = float(phase or 0.0)
            self.update()

        def paintEvent(self, _ev):
            if not self._text:
                return
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

            w = self.width()
            h = self.height()
            accent_r, accent_g, accent_b = _hex_to_rgb(self._accent)

            pad = 6
            rect = QtCore.QRectF(pad, pad, w - pad * 2, h - pad * 2)

            for i in range(4, 0, -1):
                g = QtGui.QColor(accent_r, accent_g, accent_b, int(45 * (i / 4.0)))
                p.setPen(QtGui.QPen(g, 1.0 + i * 0.9))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-i, -i, i, i), 14 + i, 14 + i)

            bg = QtGui.QColor(8, 16, 24, 170)
            p.setPen(QtGui.QPen(QtGui.QColor(70, 120, 160, 140), 1.0))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 14, 14)

            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(accent_r, accent_g, accent_b, 210))
            bar = QtCore.QRectF(rect.left() + 10, rect.top() + 10, 3.0, rect.height() - 20)
            p.drawRoundedRect(bar, 2, 2)

            p.setPen(QtGui.QColor(235, 248, 255, 245))
            p.setFont(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
            p.drawText(
                QtCore.QRectF(rect.left() + 20, rect.top(), rect.width() - 26, rect.height()),
                QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                self._text,
            )
            p.end()

    class HandleWindow(QtWidgets.QWidget):
        def __init__(self, hud_win: HudWindow):
            super().__init__()
            self.hud_win = hud_win
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.resize(geom.HANDLE_W, geom.HANDLE_H)
            self._accent = "#00FFA6"
            self._dragging = False
            self._mx0 = 0
            self._my0 = 0
            self._hx0 = 20
            self._hy0 = 20

        def setAccent(self, accent):
            self._accent = accent
            self.update()

        def mousePressEvent(self, e: "QtGui.QMouseEvent"):
            if e.button() == QtCore.Qt.LeftButton:
                self._dragging = True
                self._mx0 = int(e.globalPosition().x())
                self._my0 = int(e.globalPosition().y())
                self._hx0 = int(self.hud_win.x())
                self._hy0 = int(self.hud_win.y())

        def mouseMoveEvent(self, e: "QtGui.QMouseEvent"):
            if not self._dragging:
                return
            mx = int(e.globalPosition().x())
            my = int(e.globalPosition().y())
            dx = mx - self._mx0
            dy = my - self._my0
            nx = self._hx0 + dx
            ny = self._hy0 + dy
            nx, ny = clamp_in_desktop(nx, ny, geom.HUD_W, geom.HUD_H)
            self.hud_win.move(nx, ny)

        def mouseReleaseEvent(self, e: "QtGui.QMouseEvent"):
            if e.button() == QtCore.Qt.LeftButton:
                self._dragging = False

        def paintEvent(self, _ev):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)

            w = self.width()
            h = self.height()
            accent_r, accent_g, accent_b = _hex_to_rgb(self._accent)
            rect = QtCore.QRectF(1, 1, w - 2, h - 2)

            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 120))
            p.drawRoundedRect(rect.translated(2, 2), 8, 8)

            p.setPen(QtGui.QPen(QtGui.QColor(70, 120, 160, 160), 1.0))
            p.setBrush(QtGui.QColor(8, 16, 24, 200))
            p.drawRoundedRect(rect, 8, 8)

            p.setPen(QtGui.QPen(QtGui.QColor(accent_r, accent_g, accent_b, 190), 1.5))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)

            p.setPen(QtGui.QPen(QtGui.QColor(235, 248, 255, 235), 2))
            y0 = (h // 2) - 6
            for i in range(3):
                yy = y0 + i * 6
                p.drawLine(8, yy, w - 8, yy)

            p.end()

    app = QtWidgets.QApplication([])
    desktop_rect = desktop_union_rect_qt()

    hud_win = HudWindow()
    tip_win = TipWindow()
    handle_win = HandleWindow(hud_win)

    hud_win.move(*clamp_in_desktop(20, 20, geom.HUD_W, geom.HUD_H))
    hud_win.show()
    tip_win.hide()
    handle_win.show()

    # -------------------------------------------------------------
    # ✅ Win11: 초기 표시 실패(안 보임) 케이스 대응 유틸
    # -------------------------------------------------------------
    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040

    def _set_topmost(hwnd_int: int):
        try:
            hwnd_int = int(hwnd_int or 0)
            if hwnd_int <= 0:
                return
            user32.SetWindowPos(
                wintypes.HWND(hwnd_int),
                wintypes.HWND(HWND_TOPMOST),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        except Exception:
            pass

    def force_refresh_windows():
        # show/raise 후 topmost 재적용 + exstyle 재적용
        try:
            for w in (hud_win, handle_win, tip_win):
                try:
                    w.show()
                except Exception:
                    pass
                try:
                    w.raise_()
                except Exception:
                    pass
                try:
                    _set_topmost(int(w.winId()))
                except Exception:
                    pass

            try:
                _apply_win_exstyle(int(hud_win.winId()), click_through=True)
                _apply_win_exstyle(int(tip_win.winId()), click_through=True)
                _apply_win_exstyle(int(handle_win.winId()), click_through=False)
            except Exception:
                pass
        except Exception:
            pass

    # 첫 300ms 후 1회 강제 (부팅 직후/표시설정 토글 전 케이스)
    QtCore.QTimer.singleShot(300, force_refresh_windows)

    try:
        _apply_win_exstyle(int(hud_win.winId()), click_through=True)
        _apply_win_exstyle(int(tip_win.winId()), click_through=True)
        _apply_win_exstyle(int(handle_win.winId()), click_through=False)
    except Exception:
        pass

    def position_handle():
        hx = int(hud_win.x()) + geom.HUD_W - geom.HANDLE_W - geom.HANDLE_PAD_R
        hy = int(hud_win.y()) + geom.HANDLE_PAD_T
        hx, hy = clamp_in_desktop(hx, hy, geom.HANDLE_W, geom.HANDLE_H)
        handle_win.move(hx, hy)

    def update_tip(panel_visible_local: bool):
        cur = QCursor.pos()
        osx, osy = int(cur.x()), int(cur.y())

        mode = _mode_of(latest)
        locked = bool(latest.get("locked", False))
        bubble = _bubble_text(latest, mode, locked).strip()
        if (not panel_visible_local) or (not bubble):
            tip_win.hide()
            return

        fm = QtGui.QFontMetrics(QtGui.QFont("Segoe UI", 10, QtGui.QFont.Bold))
        text_w = fm.horizontalAdvance(bubble)
        w = max(geom.TIP_W_MIN, min(geom.TIP_W_MAX, text_w + 18 * 2 + 18))
        h = geom.TIP_H

        tx = osx + geom.TIP_OX
        ty = osy + geom.TIP_OY
        tx, ty = clamp_in_desktop(tx, ty, w, h)

        tip_win.resize(w, h)
        tip_win.move(tx, ty)
        tip_win.show()

    menu_start()

    timer = QtCore.QTimer()
    timer.setInterval(16)

    def tick():
        nonlocal latest, panel_visible, menu_active, menu_hover
        nonlocal menu_frozen_center, prev_menu_active
        nonlocal phase, last_t, desktop_rect

        stop_now = False

        # ---------------------------------------------------------
        # ✅ cmd 먼저 처리 -> status 반영
        # ---------------------------------------------------------
        try:
            while True:
                item = cmd_q.get_nowait()
                if not isinstance(item, dict):
                    continue

                cmd = item.get("__cmd")

                if cmd == "STOP":
                    stop_now = True
                    break

                if cmd == "SET_VISIBLE":
                    panel_visible = bool(item.get("visible", True))
                    continue

                if cmd == "SET_MENU":
                    menu_active = bool(item.get("active", False))
                    if not menu_active:
                        menu_hover = None
                        _evt_forward({"type": "HOVER", "value": None})
                    continue

                if cmd == "FORCE_REFRESH":
                    try:
                        force_refresh_windows()
                    except Exception:
                        pass
                    continue

                # status payload
                latest = item
                if "hudVisible" in latest:
                    panel_visible = bool(latest.get("hudVisible"))
                elif "panelVisible" in latest:
                    panel_visible = bool(latest.get("panelVisible"))

        except Exception:
            pass

        if stop_now:
            timer.stop()
            try:
                tip_win.hide()
                handle_win.hide()
                hud_win.hide()
            except Exception:
                pass
            menu_stop()
            _release_single_instance(mutex_h)
            app.quit()
            return

        desktop_rect = desktop_union_rect_qt()

        nowt = time.time()
        dt = max(1e-6, nowt - last_t)
        last_t = nowt
        phase += dt

        menu_pump_events()

        mode = _mode_of(latest)

        # Freeze center when menu becomes active
        if (not prev_menu_active) and menu_active:
            cur = QCursor.pos()
            menu_frozen_center = (int(cur.x()), int(cur.y()))
            _log("[HUD] menu frozen center:", menu_frozen_center)
        if prev_menu_active and (not menu_active):
            menu_frozen_center = None
        prev_menu_active = bool(menu_active)

        # Sync menu
        menu_sync(active=menu_active, center_xy=menu_frozen_center, mode=mode)

        # show/hide HUD & tip
        if panel_visible:
            hud_win.show()
            handle_win.show()
        else:
            hud_win.hide()
            handle_win.hide()
            tip_win.hide()

        accent = THEME[mode]["accent"]
        tracking = bool(latest.get("tracking", latest.get("isTracking", False)))
        locked = bool(latest.get("locked", False))
        gesture = str(latest.get("gesture", "NONE"))
        fps = float(latest.get("fps", 0.0) or 0.0)
        connected = bool(latest.get("connected", True))

        hud_win.setState(mode, accent, tracking, locked, gesture, fps, connected, phase, menu_active=menu_active)
        position_handle()

        bubble = _bubble_text(latest, mode, locked).strip()
        tip_win.setState(bubble, accent, phase)
        update_tip(panel_visible)

        # re-apply styles occasionally (OS가 exstyle 깨는 경우 방지)
        if int(phase * 60) % 180 == 0:
            try:
                _apply_win_exstyle(int(hud_win.winId()), click_through=True)
                _apply_win_exstyle(int(tip_win.winId()), click_through=True)
                _apply_win_exstyle(int(handle_win.winId()), click_through=False)
            except Exception:
                pass

    timer.timeout.connect(tick)
    timer.start()

    try:
        app.exec()
    except Exception as e:
        _log("[HUD] app.exec exception:", repr(e))

    try:
        menu_stop()
    except Exception:
        pass
    _release_single_instance(mutex_h)


# =========================
# PUBLIC API
# =========================
class OverlayHUD:
    _GLOBAL_LOCK = mp.Lock()
    _GLOBAL_STARTED = False

    def __init__(self, enable=True):
        self.enable = bool(enable) and (os.name == "nt")
        self._proc = None
        self._cmd_q = None
        self._evt_q = None

        self._menu_active = False
        self._menu_hover = None

        # ✅ hover latch (핵심)
        self._menu_hover_keep_until = 0.0  # epoch seconds

        self._evt_stop = threading.Event()
        self._evt_thread = None

        atexit.register(self.stop)

    def _evt_loop(self):
        """
        Consume events from HUD process.
        HOVER latch:
          - If value is str: set hover and keep for 0.35s
          - If value is None/empty: only clear after keep_until (unless menu inactive)
        """
        while (not self._evt_stop.is_set()) and self._evt_q:
            try:
                ev = self._evt_q.get(timeout=0.25)
            except Exception:
                continue
            if not isinstance(ev, dict):
                continue

            typ = str(ev.get("type", "")).upper()

            if typ == "MENU_ACTIVE":
                self._menu_active = bool(ev.get("value", False))
                if not self._menu_active:
                    self._menu_hover = None
                    self._menu_hover_keep_until = 0.0

            elif typ == "HOVER":
                v = ev.get("value", None)
                nowt = time.time()

                if isinstance(v, str) and v.strip():
                    self._menu_hover = v.strip().upper()
                    self._menu_hover_keep_until = nowt + 0.35  # ✅ 350ms latch
                else:
                    if (not self._menu_active) or (nowt >= self._menu_hover_keep_until):
                        self._menu_hover = None

    def start(self):
        if not self.enable:
            return

        with OverlayHUD._GLOBAL_LOCK:
            if OverlayHUD._GLOBAL_STARTED:
                return
            OverlayHUD._GLOBAL_STARTED = True

        if self._proc is not None and self._proc.is_alive():
            return

        try:
            mp.freeze_support()
            self._cmd_q = mp.Queue()
            self._evt_q = mp.Queue()
            self._proc = mp.Process(target=_hud_process_main, args=(self._cmd_q, self._evt_q), daemon=False)
            self._proc.start()

            self._evt_stop.clear()
            self._evt_thread = threading.Thread(target=self._evt_loop, daemon=True)
            self._evt_thread.start()

        except Exception as e:
            _log("[HUD] HUD process start failed:", repr(e))

    def stop(self):
        if not self.enable:
            return

        with OverlayHUD._GLOBAL_LOCK:
            OverlayHUD._GLOBAL_STARTED = False

        try:
            self._evt_stop.set()
        except Exception:
            pass

        try:
            if self._cmd_q:
                try:
                    self._cmd_q.put({"__cmd": "STOP"})
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if self._proc:
                self._proc.join(timeout=1.0)
        except Exception:
            pass

        try:
            if self._evt_thread and self._evt_thread.is_alive():
                self._evt_thread.join(timeout=0.5)
        except Exception:
            pass

        self._proc = None
        self._cmd_q = None
        self._evt_q = None
        self._evt_thread = None

        self._menu_active = False
        self._menu_hover = None
        self._menu_hover_keep_until = 0.0

    def push(self, status: dict):
        if not self.enable:
            return
        if not isinstance(status, dict):
            return
        if not self._cmd_q:
            return
        try:
            self._cmd_q.put_nowait(status)
        except Exception:
            pass

    def force_refresh(self):
        """
        Win11 초기 표시 실패 케이스 대응:
        HUD 프로세스에 3창(HUD/Tip/Handle) TOPMOST+show 강제 명령 전송
        """
        if not self.enable or not self._cmd_q:
            return
        try:
            self._cmd_q.put_nowait({"__cmd": "FORCE_REFRESH"})
        except Exception:
            pass

    def set_visible(self, visible: bool):
        if not self.enable or not self._cmd_q:
            return
        try:
            self._cmd_q.put_nowait({"__cmd": "SET_VISIBLE", "visible": bool(visible)})
        except Exception:
            pass

    def set_menu(self, active: bool, center_xy=None):
        if not self.enable or not self._cmd_q:
            return

        payload = {"__cmd": "SET_MENU", "active": bool(active)}

        if center_xy is not None:
            try:
                x, y = center_xy
                payload["center"] = (int(x), int(y))
            except Exception:
                pass

        try:
            self._cmd_q.put_nowait(payload)
        except Exception:
            pass

        self._menu_active = bool(active)
        if not active:
            self._menu_hover = None
            self._menu_hover_keep_until = 0.0

    def show_menu(self, center_xy=None):
        self.set_menu(True, center_xy=center_xy)

    def hide_menu(self):
        self.set_menu(False)

    def is_menu_active(self) -> bool:
        return bool(self._menu_active)

    def get_menu_hover(self):
        return self._menu_hover
