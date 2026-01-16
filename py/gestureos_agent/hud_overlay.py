# gestureos_agent/hud_overlay.py
# Windows only: Always-on-top transparent HUD overlay (click-through)
# - HUD (top-left) + Reticle (follows OS cursor) + Tip bubble (follows OS cursor)
# - Handle window is clickable to drag-move HUD (HUD stays click-through)
# - MODE menu overlay is a separate PySide6 process (qt_menu_overlay.py)

import os
import threading
import queue
import ctypes
from ctypes import wintypes
import tkinter as tk
import time
import math
import atexit
import multiprocessing as mp

HUD_DEBUG = (os.getenv("HUD_DEBUG", "0") == "1")
LOG_PATH = os.path.join(os.getenv("TEMP", "."), "GestureOS_HUD.log")

def _log(*args):
    try:
        s = " ".join(str(x) for x in args)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {s}\n")
    except Exception:
        pass


# ---- try import Qt process entry (패키지/루트 둘 다 지원) ----
run_menu_process = None
_import_errs = []
try:
    from gestureos_agent.qt_menu_overlay import run_menu_process as _rmp
    run_menu_process = _rmp
except Exception as e1:
    _import_errs.append(repr(e1))
    try:
        # 파일이 py/qt_menu_overlay.py(루트)에 있을 때
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
GWL_WNDPROC = -4

WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_NOACTIVATE  = 0x08000000

LWA_COLORKEY = 0x00000001

WM_NCHITTEST   = 0x0084
HTTRANSPARENT  = -1

GA_ROOT = 2

SWP_NOSIZE       = 0x0001
SWP_NOMOVE       = 0x0002
SWP_NOZORDER     = 0x0004
SWP_NOACTIVATE   = 0x0010
SWP_FRAMECHANGED = 0x0020

SM_XVIRTUALSCREEN  = 76
SM_YVIRTUALSCREEN  = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---- Single instance mutex (cross-process) ----
HUD_MUTEX_NAME = "Global\\GestureOS_HUD_Overlay_SingleInstance"
ERROR_ALREADY_EXISTS = 183

kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.GetLastError.restype = wintypes.DWORD
kernel32.CloseHandle.restype = wintypes.BOOL

# IMPORTANT: must match colorkey used in SetLayeredWindowAttributes
TRANSPARENT = "#010101"


# ---- 64-bit safe: Get/SetWindowLongPtr fallback ----
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


# APIs
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD
]

user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT
]

user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]

user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]

user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.CallWindowProcW.argtypes = [
    ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


# ---- Reticle image assets (mode -> png) ----
ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets", "reticle")
RETICLE_PNG = {
    "MOUSE": "mouse.png",
    "DRAW": "draw.png",
    "PRESENTATION": "ppt.png",
    "KEYBOARD": "keyboard.png",
    "RUSH": "rush.png",
    "RUSH_HAND": "rush.png",
    "RUSH_COLOR": "rush.png",
    "VKEY": "keyboard.png",
    "DEFAULT": "mouse.png",
}

# ---- Theme per mode (HUD colors) ----
THEME = {
    "MOUSE":        {"accent": "#22c55e"},
    "DRAW":         {"accent": "#f59e0b"},
    "PRESENTATION": {"accent": "#60a5fa"},
    "KEYBOARD":     {"accent": "#a78bfa"},
    "RUSH":         {"accent": "#f472b6"},
    "RUSH_HAND":    {"accent": "#f472b6"},
    "RUSH_COLOR":   {"accent": "#f472b6"},
    "VKEY":         {"accent": "#34d399"},
    "DEFAULT":      {"accent": "#22c55e"},
}


def _mode_of(status: dict) -> str:
    m = str(status.get("mode", "DEFAULT")).upper()
    return m if m in THEME else "DEFAULT"


def _hex_dim(color_hex, a):
    color_hex = str(color_hex).lstrip("#")
    r = int(color_hex[0:2], 16)
    g = int(color_hex[2:4], 16)
    b = int(color_hex[4:6], 16)
    r = max(0, min(255, int(r * a)))
    g = max(0, min(255, int(g * a)))
    b = max(0, min(255, int(b * a)))
    return f"#{r:02x}{g:02x}{b:02x}"


class OverlayHUD:
    _GLOBAL_LOCK = threading.Lock()
    _GLOBAL_STARTED = False

    def __init__(self, enable=True):
        self.enable = bool(enable) and (os.name == "nt")
        self._q = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = None
        self._latest = {}
        self._phase = 0.0
        self._ct_tick = 0

        # panel visibility
        self._panel_visible = True

        # menu state (Qt overlay)
        self._menu_active = False
        self._menu_center = None
        self._menu_hover = None

        # drag state (handle)
        self._dragging = False
        self._drag_mx0 = 0
        self._drag_my0 = 0
        self._drag_hud_x0 = 0
        self._drag_hud_y0 = 0

        # virtual screen
        self.vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        self.vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        self.vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        self.vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        # tk objects
        self._root = None
        self._hud_win = None
        self._ret_win = None
        self._tip_win = None
        self._handle_win = None

        self._hud_canvas = None
        self._ret_canvas = None
        self._tip_canvas = None
        self._handle_canvas = None

        # geometry
        self.HUD_W, self.HUD_H = 320, 118
        self.RET_S = 48

        self.TIP_W, self.TIP_H = 260, 46
        self.TIP_OX, self.TIP_OY = 26, -66

        self.HANDLE_W, self.HANDLE_H = 30, 26
        self.HANDLE_PAD_R = 14
        self.HANDLE_PAD_T = 14

        # wndproc hooks
        self._old_wndproc = {}
        self._new_wndproc_ref = {}

        # reticle images
        self._ret_imgs = {}
        self._ret_img_item = None
        self._ret_img_mode = None

        # single-instance mutex
        self._mutex = None

        # Qt menu process
        self._qt_ok = False
        self._qt_cmd_q = None
        self._qt_evt_q = None
        self._qt_proc = None
        self._qt_last_active = None
        self._qt_last_center = None
        self._qt_last_mode = None
        self._qt_last_opacity = None

        atexit.register(self.stop)

    # ---------------- public ----------------
    def set_visible(self, visible: bool):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "SET_VISIBLE", "visible": bool(visible)})
        except Exception:
            pass

    def set_menu(self, active: bool, center_xy=None, hover: str = None):
        if not self.enable:
            return
        payload = {"__cmd": "SET_MENU", "active": bool(active)}
        if center_xy is not None:
            try:
                x, y = center_xy
                payload["center"] = (int(x), int(y))
            except Exception:
                pass
        if hover is not None:
            payload["hover"] = str(hover).upper()
        try:
            self._q.put_nowait(payload)
        except Exception:
            pass

    def show_menu(self, center_xy=None):
        # ✅ center가 None으로 들어오면 "현재 OS 커서 위치"로 강제 앵커(선택 불가 버그 방지)
        if center_xy is None:
            try:
                cx, cy = self._get_os_cursor_xy()
                if cx is not None and cy is not None:
                    center_xy = (cx, cy)
            except Exception:
                pass
        self.set_menu(True, center_xy=center_xy)

    def hide_menu(self):
        self.set_menu(False)

    def is_menu_active(self) -> bool:
        return bool(self._menu_active)

    def get_menu_hover(self):
        return self._menu_hover

    # ---------------- single instance ----------------
    def _acquire_single_instance(self) -> bool:
        if self._mutex is not None:
            return True

        h = kernel32.CreateMutexW(None, True, HUD_MUTEX_NAME)
        if not h:
            return True

        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(h)
            return False

        self._mutex = h
        return True

    def _release_single_instance(self):
        if self._mutex:
            try:
                kernel32.CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None

    # ---------------- Qt menu process ----------------
    def _qt_menu_start(self):
        if not self.enable:
            return
        if run_menu_process is None:
            self._qt_ok = False
            _log("[HUD] run_menu_process is None. Check qt_menu_overlay.py location & PySide6 install.")
            if HUD_DEBUG:
                print("[HUD] Qt menu disabled: run_menu_process is None (import failed).", flush=True)
            return

        if self._qt_proc is not None and self._qt_proc.is_alive():
            self._qt_ok = True
            return

        try:
            mp.freeze_support()

            self._qt_cmd_q = mp.Queue()
            self._qt_evt_q = mp.Queue()
            self._qt_proc = mp.Process(
                target=run_menu_process,
                args=(self._qt_cmd_q, self._qt_evt_q),
                daemon=True
            )
            self._qt_proc.start()

            self._qt_ok = True
            self._qt_last_active = None
            self._qt_last_center = None
            self._qt_last_mode = None
            self._qt_last_opacity = None

            _log("[HUD] Qt menu process started. pid=", getattr(self._qt_proc, "pid", None))
            if HUD_DEBUG:
                print("[HUD] Qt menu process started pid=", getattr(self._qt_proc, "pid", None), flush=True)

        except Exception as e:
            self._qt_ok = False
            _log("[HUD] Qt menu start failed:", repr(e))
            if HUD_DEBUG:
                print("[HUD] Qt menu start failed:", repr(e), flush=True)

    def _qt_menu_stop(self):
        try:
            if self._qt_cmd_q:
                try:
                    self._qt_cmd_q.put({"type": "QUIT"})
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if self._qt_proc:
                self._qt_proc.join(timeout=1.0)
        except Exception:
            pass

        self._qt_proc = None
        self._qt_cmd_q = None
        self._qt_evt_q = None
        self._qt_ok = False

    def _qt_send(self, msg: dict):
        if not self._qt_ok or not self._qt_cmd_q:
            return
        try:
            self._qt_cmd_q.put_nowait(msg)
        except Exception:
            pass

    def _qt_pump_events(self):
        if not self._qt_ok or not self._qt_evt_q:
            return
        while True:
            try:
                ev = self._qt_evt_q.get_nowait()
            except Exception:
                break
            if isinstance(ev, dict) and ev.get("type") == "HOVER":
                self._menu_hover = ev.get("value")

    def _qt_sync(self, active: bool, center_xy, mode: str):
        # process died? restart
        if self._qt_proc is not None and (not self._qt_proc.is_alive()):
            _log("[HUD] Qt menu process died -> restarting")
            self._qt_menu_start()

        if not self._qt_ok:
            return

        if self._qt_last_active != bool(active):
            self._qt_last_active = bool(active)
            self._qt_send({"type": "ACTIVE", "value": bool(active)})

        if bool(active):
            if center_xy is not None:
                try:
                    cx, cy = int(center_xy[0]), int(center_xy[1])
                    c = (cx, cy)
                    if self._qt_last_center != c:
                        self._qt_last_center = c
                        self._qt_send({"type": "CENTER", "value": c})
                except Exception:
                    pass

        m = str(mode or "DEFAULT").upper()
        if self._qt_last_mode != m:
            self._qt_last_mode = m
            self._qt_send({"type": "MODE", "value": m})

        if self._qt_last_opacity is None:
            self._qt_last_opacity = 0.82
            self._qt_send({"type": "OPACITY", "value": 0.82})

    # ---------------- assets ----------------
    def _load_reticle_images(self):
        self._ret_imgs = {}
        for mode, fn in RETICLE_PNG.items():
            path = os.path.join(ASSET_DIR, fn)
            if not os.path.exists(path):
                continue
            try:
                img = tk.PhotoImage(file=path)
                self._ret_imgs[mode] = img
            except Exception:
                pass

    # ---------------- lifecycle ----------------
    def start(self):
        if not self.enable:
            return

        if not self._acquire_single_instance():
            return

        with OverlayHUD._GLOBAL_LOCK:
            if OverlayHUD._GLOBAL_STARTED:
                return
            OverlayHUD._GLOBAL_STARTED = True

        self._qt_menu_start()

        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.enable:
            return

        with OverlayHUD._GLOBAL_LOCK:
            OverlayHUD._GLOBAL_STARTED = False

        self._release_single_instance()

        self._stop.set()
        try:
            self._q.put_nowait({"__cmd": "STOP"})
        except Exception:
            pass

        self._qt_menu_stop()

    def push(self, status: dict):
        if not self.enable:
            return
        if not isinstance(status, dict):
            return
        try:
            self._q.put_nowait(status)
        except Exception:
            pass

    # ---------------- internal helpers ----------------
    def _clamp_screen_xy(self, x, y, w, h):
        min_x = self.vx
        min_y = self.vy
        max_x = self.vx + self.vw - w
        max_y = self.vy + self.vh - h
        x = max(min_x, min(int(x), int(max_x)))
        y = max(min_y, min(int(y), int(max_y)))
        return x, y

    def _get_os_cursor_xy(self):
        pt = wintypes.POINT()
        ok = user32.GetCursorPos(ctypes.byref(pt))
        if not ok:
            return (None, None)
        return (int(pt.x), int(pt.y))

    def _iter_related_hwnds(self, hwnd_int: int):
        seen = set()
        base = _hwnd_int(hwnd_int)
        if base:
            seen.add(base)
            yield base

        try:
            parent = user32.GetParent(wintypes.HWND(base))
            parent_i = _hwnd_int(parent)
            if parent_i and parent_i not in seen:
                seen.add(parent_i)
                yield parent_i
        except Exception:
            pass

        try:
            root = user32.GetAncestor(wintypes.HWND(base), GA_ROOT)
            root_i = _hwnd_int(root)
            if root_i and root_i not in seen:
                seen.add(root_i)
                yield root_i
        except Exception:
            pass

    def _install_httransparent_wndproc(self, hwnd_int: int):
        hwnd_int = _hwnd_int(hwnd_int)
        if not hwnd_int:
            return
        if hwnd_int in self._old_wndproc:
            return

        try:
            hwnd = wintypes.HWND(hwnd_int)
            old_proc = _get_window_long_ptr(hwnd, GWL_WNDPROC)
            if not old_proc:
                return

            def _proc(h, msg, wparam, lparam):
                if msg == WM_NCHITTEST:
                    return HTTRANSPARENT
                return user32.CallWindowProcW(ctypes.c_void_p(old_proc), h, msg, wparam, lparam)

            new_proc = WNDPROC(_proc)
            new_proc_ptr = ctypes.cast(new_proc, ctypes.c_void_p).value
            _set_window_long_ptr(hwnd, GWL_WNDPROC, new_proc_ptr)

            self._old_wndproc[hwnd_int] = old_proc
            self._new_wndproc_ref[hwnd_int] = new_proc
        except Exception:
            pass

    def _apply_click_through_hwnd(self, hwnd_int: int):
        for hid in self._iter_related_hwnds(hwnd_int):
            try:
                hwnd = wintypes.HWND(hid)

                ex = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
                ex |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                _set_window_long_ptr(hwnd, GWL_EXSTYLE, ex)

                colorkey = wintypes.COLORREF(0x00010101)  # matches TRANSPARENT
                user32.SetLayeredWindowAttributes(hwnd, colorkey, 0, LWA_COLORKEY)

                user32.SetWindowPos(
                    hwnd, wintypes.HWND(0),
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
                )

                self._install_httransparent_wndproc(hid)
            except Exception:
                pass

    def _walk_widgets(self, w):
        yield w
        try:
            for ch in w.winfo_children():
                yield from self._walk_widgets(ch)
        except Exception:
            return

    def _apply_click_through(self, win: tk.Toplevel):
        try:
            win.update_idletasks()
            win.update()
        except Exception:
            pass

        for w in self._walk_widgets(win):
            try:
                self._apply_click_through_hwnd(w.winfo_id())
            except Exception:
                pass

    def _apply_handle_hwnd_style(self, hwnd_int: int):
        """Handle must be clickable -> NO WS_EX_TRANSPARENT."""
        hwnd_int = _hwnd_int(hwnd_int)
        if not hwnd_int:
            return
        try:
            hwnd = wintypes.HWND(hwnd_int)

            ex = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
            ex |= (WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            ex &= (~WS_EX_TRANSPARENT)
            _set_window_long_ptr(hwnd, GWL_EXSTYLE, ex)

            colorkey = wintypes.COLORREF(0x00010101)
            user32.SetLayeredWindowAttributes(hwnd, colorkey, 0, LWA_COLORKEY)

            user32.SetWindowPos(
                hwnd, wintypes.HWND(0),
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
            )
        except Exception:
            pass

    def _position_handle(self):
        if self._hud_win is None or self._handle_win is None:
            return
        try:
            hx = int(self._hud_win.winfo_x()) + self.HUD_W - self.HANDLE_W - self.HANDLE_PAD_R
            hy = int(self._hud_win.winfo_y()) + self.HANDLE_PAD_T
            hx, hy = self._clamp_screen_xy(hx, hy, self.HANDLE_W, self.HANDLE_H)
            self._handle_win.geometry(f"{self.HANDLE_W}x{self.HANDLE_H}+{hx}+{hy}")
        except Exception:
            pass

    # ---------------- bubble text helpers ----------------
    @staticmethod
    def _pick_first_str(st: dict, keys):
        for k in keys:
            v = st.get(k, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _common_state_label(self, st: dict, locked: bool):
        enabled = bool(st.get("enabled", True))
        if not enabled:
            return "비활성"
        if locked:
            return "잠김"
        return None

    def _action_mouse(self, st: dict, locked: bool) -> str:
        common = self._common_state_label(st, locked)
        if common:
            return common
        if bool(st.get("scrollActive", False)):
            return "스크롤"
        g = str(st.get("gesture", "NONE") or "NONE").upper()
        if g == "OPEN_PALM":
            return "이동"
        if g == "PINCH_INDEX":
            return "클릭/드래그"
        if g == "V_SIGN":
            return "우클릭"
        if g == "FIST":
            return "잠금(홀드)"
        return "대기"

    def _action_draw(self, st: dict, locked: bool) -> str:
        common = self._common_state_label(st, locked)
        if common:
            return common
        tool = self._pick_first_str(st, ["tool", "drawTool", "brush", "pen", "eraser"])
        if tool:
            return f"{tool}"
        g = str(st.get("gesture", "NONE") or "NONE").upper()
        if g == "PINCH_INDEX":
            return "그리기"
        if g == "OPEN_PALM":
            return "이동"
        if g == "V_SIGN":
            return "도구변경"
        if g == "FIST":
            return "지우기(홀드)"
        return "대기"

    def _action_presentation(self, st: dict, locked: bool) -> str:
        common = self._common_state_label(st, locked)
        if common:
            return common
        act = self._pick_first_str(st, ["pptAction", "presentationAction", "slideAction", "action"])
        if act:
            return act
        g = str(st.get("gesture", "NONE") or "NONE").upper()
        if g == "V_SIGN":
            return "다음"
        if g == "FIST":
            return "이전"
        if g == "PINCH_INDEX":
            return "클릭"
        if g == "OPEN_PALM":
            return "포인터"
        return "대기"

    def _action_keyboard(self, st: dict, locked: bool) -> str:
        common = self._common_state_label(st, locked)
        if common:
            return common
        sel = self._pick_first_str(st, ["selectedKey", "key", "keyName", "char"])
        g = str(st.get("gesture", "NONE") or "NONE").upper()
        if g == "PINCH_INDEX":
            return f"입력({sel})" if sel else "입력"
        if g == "OPEN_PALM":
            return "선택"
        if sel:
            return f"선택({sel})"
        return "대기"

    def _action_vkey(self, st: dict, locked: bool) -> str:
        common = self._common_state_label(st, locked)
        if common:
            return common
        sel = self._pick_first_str(st, ["vk", "vkey", "selectedKey", "key", "keyName", "char"])
        g = str(st.get("gesture", "NONE") or "NONE").upper()
        if g == "PINCH_INDEX":
            return f"입력({sel})" if sel else "입력"
        if g == "OPEN_PALM":
            return "선택"
        if sel:
            return f"선택({sel})"
        return "대기"

    def _action_default(self, st: dict, locked: bool) -> str:
        common = self._common_state_label(st, locked)
        if common:
            return common
        g = str(st.get("gesture", "NONE") or "NONE").strip()
        if g and g.upper() != "NONE":
            return g
        return "대기"

    def _bubble_text(self, st: dict, mode: str, locked: bool) -> str:
        mode_u = str(mode).upper()
        if mode_u.startswith("RUSH"):
            return ""

        bubble = st.get("cursorBubble", None)
        if bubble is not None:
            return str(bubble).strip()

        if mode_u == "MOUSE":
            action = self._action_mouse(st, locked)
        elif mode_u == "DRAW":
            action = self._action_draw(st, locked)
        elif mode_u == "PRESENTATION":
            action = self._action_presentation(st, locked)
        elif mode_u == "KEYBOARD":
            action = self._action_keyboard(st, locked)
        elif mode_u == "VKEY":
            action = self._action_vkey(st, locked)
        else:
            action = self._action_default(st, locked)

        action = str(action).strip() if action is not None else ""
        return f"{mode_u} • {action}" if action else mode_u

    # ---------------- tk thread ----------------
    def _run_tk(self):
        root = tk.Tk()
        self._root = root
        root.withdraw()

        # HUD window
        hud = tk.Toplevel(root)
        self._hud_win = hud
        hud.overrideredirect(True)
        hud.attributes("-topmost", True)
        hud.configure(bg=TRANSPARENT)
        try:
            hud.wm_attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass
        hud.geometry(f"{self.HUD_W}x{self.HUD_H}+20+20")

        hud_canvas = tk.Canvas(
            hud, width=self.HUD_W, height=self.HUD_H,
            bd=0, highlightthickness=0, bg=TRANSPARENT
        )
        hud_canvas.pack(fill="both", expand=True)
        self._hud_canvas = hud_canvas

        # Handle window (clickable)
        handle = tk.Toplevel(root)
        self._handle_win = handle
        handle.overrideredirect(True)
        handle.attributes("-topmost", True)
        handle.configure(bg=TRANSPARENT)
        try:
            handle.wm_attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass
        handle.geometry(f"{self.HANDLE_W}x{self.HANDLE_H}+20+20")

        handle_canvas = tk.Canvas(
            handle, width=self.HANDLE_W, height=self.HANDLE_H,
            bd=0, highlightthickness=0, bg=TRANSPARENT
        )
        handle_canvas.pack(fill="both", expand=True)
        self._handle_canvas = handle_canvas

        try:
            handle.update_idletasks()
            self._apply_handle_hwnd_style(handle.winfo_id())
        except Exception:
            pass

        # Bind drag on handle
        def _on_press(e):
            self._dragging = True
            self._drag_mx0 = e.x_root
            self._drag_my0 = e.y_root
            try:
                self._drag_hud_x0 = int(hud.winfo_x())
                self._drag_hud_y0 = int(hud.winfo_y())
            except Exception:
                self._drag_hud_x0 = 20
                self._drag_hud_y0 = 20

        def _on_drag(e):
            if not self._dragging:
                return
            dx = int(e.x_root - self._drag_mx0)
            dy = int(e.y_root - self._drag_my0)
            nx = self._drag_hud_x0 + dx
            ny = self._drag_hud_y0 + dy
            nx, ny = self._clamp_screen_xy(nx, ny, self.HUD_W, self.HUD_H)
            try:
                hud.geometry(f"{self.HUD_W}x{self.HUD_H}+{nx}+{ny}")
            except Exception:
                pass
            self._position_handle()

        def _on_release(_e):
            self._dragging = False

        for ww in (handle, handle_canvas):
            ww.bind("<ButtonPress-1>", _on_press)
            ww.bind("<B1-Motion>", _on_drag)
            ww.bind("<ButtonRelease-1>", _on_release)

        # Reticle window
        ret = tk.Toplevel(root)
        self._ret_win = ret
        ret.overrideredirect(True)
        ret.attributes("-topmost", True)
        ret.configure(bg=TRANSPARENT)
        try:
            ret.wm_attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass
        ret.geometry(f"{self.RET_S}x{self.RET_S}+{self.vx}+{self.vy}")

        ret_canvas = tk.Canvas(
            ret, width=self.RET_S, height=self.RET_S,
            bd=0, highlightthickness=0, bg=TRANSPARENT
        )
        ret_canvas.pack(fill="both", expand=True)
        self._ret_canvas = ret_canvas

        # Tip window
        tip = tk.Toplevel(root)
        self._tip_win = tip
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=TRANSPARENT)
        try:
            tip.wm_attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass
        tip.geometry(f"{self.TIP_W}x{self.TIP_H}+{self.vx}+{self.vy}")

        tip_canvas = tk.Canvas(
            tip, width=self.TIP_W, height=self.TIP_H,
            bd=0, highlightthickness=0, bg=TRANSPARENT
        )
        tip_canvas.pack(fill="both", expand=True)
        self._tip_canvas = tip_canvas

        # Disable input at Tk level (extra safety) - keep handle clickable
        for w in (hud, ret, tip):
            try:
                w.attributes("-disabled", True)
            except Exception:
                pass

        # Click-through hardening (handle 제외!)
        self._apply_click_through(hud)
        self._apply_click_through(ret)
        self._apply_click_through(tip)

        # Load images AFTER Tk init
        self._load_reticle_images()

        # Create reticle image item ONCE
        img0 = self._ret_imgs.get("DEFAULT")
        if img0 is None and self._ret_imgs:
            img0 = next(iter(self._ret_imgs.values()), None)
        if img0 is not None:
            self._ret_img_item = ret_canvas.create_image(
                self.RET_S // 2, self.RET_S // 2,
                image=img0, anchor="center",
                tags=("RETICLE_IMG",)
            )
            self._ret_img_mode = "DEFAULT"

        self._position_handle()
        last_t = time.time()

        def tick():
            nonlocal last_t

            if self._stop.is_set():
                for w in (hud, handle, ret, tip, root):
                    try:
                        w.destroy()
                    except Exception:
                        pass
                return

            latest = None
            stop_cmd = False
            try:
                while True:
                    item = self._q.get_nowait()

                    if isinstance(item, dict) and item.get("__cmd") == "STOP":
                        stop_cmd = True
                        break

                    if isinstance(item, dict) and item.get("__cmd") == "SET_VISIBLE":
                        self._panel_visible = bool(item.get("visible", True))
                        continue

                    if isinstance(item, dict) and item.get("__cmd") == "SET_MENU":
                        self._menu_active = bool(item.get("active", False))
                        if "center" in item:
                            self._menu_center = item.get("center", None)
                        continue

                    latest = item
            except Exception:
                pass

            if stop_cmd:
                self._stop.set()
                root.after(0, tick)
                return

            if isinstance(latest, dict):
                self._latest = latest
                if "hudVisible" in latest:
                    self._panel_visible = bool(latest.get("hudVisible"))
                elif "panelVisible" in latest:
                    self._panel_visible = bool(latest.get("panelVisible"))

            nowt = time.time()
            dt = max(1e-6, nowt - last_t)
            last_t = nowt
            self._phase += dt

            # pump qt hover events
            self._qt_pump_events()

            self._render()

            # Periodically re-apply click-through (some environments lose it)
            self._ct_tick += 1
            if (self._ct_tick % 60) == 0:
                for w in (hud, ret, tip):
                    self._apply_click_through(w)
                    try:
                        w.attributes("-disabled", True)
                    except Exception:
                        pass
                try:
                    self._apply_handle_hwnd_style(handle.winfo_id())
                except Exception:
                    pass

            root.after(16, tick)

        root.after(0, tick)
        try:
            root.mainloop()
        except Exception:
            pass

    def _draw_handle(self, accent: str):
        hc = self._handle_canvas
        if hc is None:
            return
        hc.delete("all")

        bg = "#0b1222"
        border = _hex_dim(accent, 0.85)
        fg = "#E5E7EB"

        hc.create_rectangle(1, 1, self.HANDLE_W - 1, self.HANDLE_H - 1, fill=bg, outline=border, width=2)

        y0 = (self.HANDLE_H // 2) - 6
        for i in range(3):
            yy = y0 + i * 6
            hc.create_line(8, yy, self.HANDLE_W - 8, yy, fill=fg, width=2)

    def _render(self):
        st = self._latest if isinstance(self._latest, dict) else {}
        mode = _mode_of(st)
        accent = THEME[mode]["accent"]

        tracking = bool(st.get("tracking", st.get("isTracking", False)))
        locked = bool(st.get("locked", False))
        gesture = str(st.get("gesture", "NONE"))
        fps = float(st.get("fps", 0.0) or 0.0)
        connected = bool(st.get("connected", True))

        # HUD panel show/hide
        if self._hud_win is not None and self._handle_win is not None:
            try:
                if self._panel_visible:
                    self._hud_win.deiconify()
                    self._handle_win.deiconify()
                else:
                    self._hud_win.withdraw()
                    self._handle_win.withdraw()
                    if self._tip_win is not None:
                        self._tip_win.withdraw()
            except Exception:
                pass

        if self._panel_visible:
            self._position_handle()
            self._draw_handle(accent)

        # HUD draw
        c = self._hud_canvas
        if c is not None and self._panel_visible:
            c.delete("all")

            bg = "#08101f"
            border = _hex_dim(accent, 0.80)
            fg = "#E5E7EB"
            sub = "#9CA3AF"

            c.create_rectangle(8, 8, self.HUD_W - 8, self.HUD_H - 8, fill=bg, outline=border, width=2)
            c.create_rectangle(8, 8, 14, self.HUD_H - 8, fill=accent, outline="")

            dot = "#22c55e" if connected else "#ef4444"
            c.create_oval(20, 18, 28, 26, fill=dot, outline="")
            c.create_text(34, 22, anchor="w", fill=fg, font=("Segoe UI", 11, "bold"), text=mode)

            pill_text = "LOCK" if locked else "OK"
            pill_fill = "#f59e0b" if locked else _hex_dim(accent, 0.55)
            pill_x1 = self.HUD_W - 16 - (self.HANDLE_W + 10)
            pill_x0 = pill_x1 - 70
            c.create_rectangle(pill_x0, 14, pill_x1, 34, fill=pill_fill, outline="")
            c.create_text((pill_x0 + pill_x1) // 2, 24, fill="#050a14", font=("Segoe UI", 9, "bold"), text=pill_text)

            c.create_text(20, 52, anchor="w", fill=sub, font=("Segoe UI", 9), text=f"GESTURE: {gesture}")
            c.create_text(20, 70, anchor="w", fill=sub, font=("Segoe UI", 9), text=f"TRACK: {'ON' if tracking else 'OFF'}")
            c.create_text(self.HUD_W - 20, 70, anchor="e", fill=sub, font=("Segoe UI", 9), text=f"{fps:.1f} FPS")

            base_y = 96
            for i in range(0, 12):
                x = 20 + i * 24
                amp = 6 if tracking else 2
                y = base_y + math.sin(self._phase * 2.2 + i * 0.55) * amp
                c.create_line(x, base_y, x + 18, y, fill=_hex_dim(accent, 0.55), width=2)

        # OS cursor
        osx, osy = self._get_os_cursor_xy()
        if osx is None or osy is None:
            return

        # ---- Qt menu sync (active/center/mode) ----
        self._qt_sync(active=self._menu_active, center_xy=self._menu_center, mode=mode)

        # Reticle
        if self._ret_win is not None and self._ret_canvas is not None:
            try:
                self._ret_win.deiconify()
            except Exception:
                pass

            gx = osx - self.RET_S // 2
            gy = osy - self.RET_S // 2
            gx, gy = self._clamp_screen_xy(gx, gy, self.RET_S, self.RET_S)
            try:
                self._ret_win.geometry(f"{self.RET_S}x{self.RET_S}+{gx}+{gy}")
            except Exception:
                pass

            key = mode if mode in self._ret_imgs else "DEFAULT"
            img = self._ret_imgs.get(key) or self._ret_imgs.get("DEFAULT")

            if img is None:
                try:
                    self._ret_win.withdraw()
                except Exception:
                    pass
            else:
                if self._ret_img_item is None:
                    self._ret_img_item = self._ret_canvas.create_image(
                        self.RET_S // 2, self.RET_S // 2,
                        image=img, anchor="center",
                        tags=("RETICLE_IMG",)
                    )
                else:
                    self._ret_canvas.itemconfig(self._ret_img_item, image=img)
                self._ret_img_mode = key

        # Tip bubble
        tipw = self._tip_win
        tipc = self._tip_canvas
        if tipw is None or tipc is None:
            return

        if not self._panel_visible:
            try:
                tipw.withdraw()
            except Exception:
                pass
            return

        bubble = self._bubble_text(st, mode, locked).strip()
        if not bubble:
            try:
                tipw.withdraw()
            except Exception:
                pass
            return

        try:
            tipw.deiconify()
        except Exception:
            pass

        tx = osx + self.TIP_OX
        ty = osy + self.TIP_OY
        tx, ty = self._clamp_screen_xy(tx, ty, self.TIP_W, self.TIP_H)

        try:
            tipw.geometry(f"{self.TIP_W}x{self.TIP_H}+{tx}+{ty}")
        except Exception:
            pass

        tipc.delete("all")
        tip_bg = "#0b1222"
        tip_border = _hex_dim(accent, 0.92)
        tip_fg = "#E5E7EB"

        pad = 8
        tail_h = 8
        x0, y0 = pad, pad
        x1 = self.TIP_W - pad
        y1 = self.TIP_H - pad - tail_h

        tipc.create_rectangle(x0, y0, x1, y1, fill=tip_bg, outline=tip_border, width=2)
        tail_x = x0 + 18
        tipc.create_polygon(
            tail_x, y1,
            tail_x + 12, y1,
            tail_x + 6, y1 + tail_h,
            fill=tip_bg, outline=tip_border, width=2
        )
        tipc.create_text(
            (x0 + x1) // 2, (y0 + y1) // 2,
            fill=tip_fg, font=("Segoe UI", 10, "bold"),
            text=bubble
        )
