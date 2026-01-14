# gestureos_agent/hud_overlay.py
# Windows only: Always-on-top transparent HUD overlay (click-through)
# - HUD (top-left) + Reticle (follows pointer) + Tip bubble (follows pointer)
# - Tip bubble: ALL modes EXCEPT RUSH (RUSH = no bubble)
# - Bubble text style: "MODE • action"
# - Apply click-through to: widget hwnd + parent hwnd + root/ancestor hwnd + all descendants
# - Hard fix: WM_NCHITTEST -> HTTRANSPARENT (subclass WndProc)
# - Extra safety: Tk '-disabled' attribute (very effective on Win10/11)
#
# ✅ Added:
# - Clickable "handle" window (☰) to drag-move the HUD panel WITHOUT breaking click-through.
#   (HUD/reticle/tip remain click-through; only the small handle is clickable.)
# - Proper overlay/hud visibility gating so withdraw() doesn't get undone by _render().
# - Handle follows HUD for all move commands + drag.
# - Pill(LOCK/OK) shifted left to avoid overlap with handle (handle keeps its position)
#
# ✅ NOTE:
# - Drag is ALWAYS enabled (no drag on/off toggle).

import os
import threading
import queue
import ctypes
from ctypes import wintypes
import tkinter as tk
import time
import math
from typing import Optional

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
    """HWND -> int (robust)"""
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
    "MOUSE": "cursor.png",
    "DRAW": "carrot01.png",
    "PRESENTATION": "cat03.png",
    "KEYBOARD": "mouse.png",
    "RUSH": "cat.png",
    "VKEY": "cat02.png",
    "DEFAULT": "cursor.png",
}

# ---- Theme per mode (HUD colors) ----
THEME = {
    "MOUSE":        {"accent": "#22c55e"},
    "DRAW":         {"accent": "#f59e0b"},
    "PRESENTATION": {"accent": "#60a5fa"},
    "KEYBOARD":     {"accent": "#a78bfa"},
    "RUSH":         {"accent": "#f472b6"},
    "VKEY":         {"accent": "#34d399"},
    "DEFAULT":      {"accent": "#22c55e"},
}

HUD_DEBUG = False
TRANSPARENT = "#ff00ff"  # colorkey magenta

def _mode_of(status: dict) -> str:
    m = str(status.get("mode", "DEFAULT")).upper()
    return m if m in THEME else "DEFAULT"

def _clamp01(v):
    try:
        v = float(v)
    except Exception:
        return None
    if v != v:
        return None
    return max(0.0, min(1.0, v))

def _normalize_pointer(x, y, screen_w, screen_h):
    if x is None or y is None:
        return (None, None)
    try:
        fx = float(x); fy = float(y)
    except Exception:
        return (None, None)

    if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0:
        return (_clamp01(fx), _clamp01(fy))

    if -1.0 <= fx <= 1.0 and -1.0 <= fy <= 1.0:
        return (_clamp01((fx + 1.0) * 0.5), _clamp01((fy + 1.0) * 0.5))

    if screen_w > 0 and screen_h > 0:
        return (_clamp01(fx / screen_w), _clamp01(fy / screen_h))

    return (None, None)

def _hex_dim(color_hex, a):
    color_hex = str(color_hex).lstrip("#")
    r = int(color_hex[0:2], 16)
    g = int(color_hex[2:4], 16)
    b = int(color_hex[4:6], 16)
    r = int(r * a); g = int(g * a); b = int(b * a)
    return f"#{r:02x}{g:02x}{b:02x}"


class OverlayHUD:
    """
    HUD + Reticle + Tip bubble (ALL modes except RUSH)
    All windows are click-through EXCEPT the small "handle" window for drag move.
    """
    def __init__(self, enable=True):
        self.enable = bool(enable) and (os.name == "nt")

        self._q = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = None
        self._latest = {}
        self._phase = 0.0
        self._ct_tick = 0

        # pointer grace (prevent reticle hide flicker / start delay)
        self._last_ptr01 = (0.5, 0.5)
        self._last_ptr_ts = 0.0
        self.PTR_GRACE_SEC = 1.5  # 끊겨도 1.5초는 마지막 위치 유지

        # virtual screen (multi-monitor)
        self.vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        self.vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        self.vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        self.vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        # tk objects (tk thread only)
        self._root = None
        self._hud_win = None
        self._ret_win = None
        self._tip_win = None
        self._hud_canvas = None
        self._ret_canvas = None
        self._tip_canvas = None

        self.HUD_W, self.HUD_H = 320, 118
        self.RET_S = 48

        # Tip bubble
        self.TIP_W, self.TIP_H = 230, 46
        self.TIP_OX, self.TIP_OY = 26, -66  # pointer 기준 offset

        # drag handle window (clickable)
        self.HANDLE_W, self.HANDLE_H = 34, 28
        self._handle_win = None
        self._handle_canvas = None
        self._handle_last_accent = None
        self._drag_start = None  # (mx, my, hud_x, hud_y)

        # wndproc hooks (keep refs to prevent GC)
        self._old_wndproc = {}     # hwnd_int -> old_proc_ptr
        self._new_wndproc_ref = {} # hwnd_int -> WNDPROC callable

        self._ret_imgs = {}
        self._ret_img_item = None
        self._ret_img_mode = None

        # anti-flicker
        self._last_track_ts = 0.0
        self._last_xy01 = None   # (x01,y01)
        self._grace_sec = 0.25   # 0.2~0.35 추천
        self._ret_visible = False

        # visibility flags
        self._overlay_visible = True     # 전체( hud+reticle+tip ) ON/OFF
        self._hud_panel_visible = True   # 좌상단 HUD 패널만 ON/OFF (옵션)

        # HUD position
        self._hud_x, self._hud_y = 20, 20

    # ---------------- public API ----------------
    def start(self):
        if not self.enable:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.enable:
            return
        self._stop.set()
        try:
            self._q.put_nowait({"__cmd": "STOP"})
        except Exception:
            pass

    def push(self, status: dict):
        if not self.enable:
            return
        if not isinstance(status, dict):
            return
        try:
            self._q.put_nowait(status)
        except Exception:
            pass

    def set_overlay_visible(self, visible: bool):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "SET_OVERLAY_VISIBLE", "visible": bool(visible)})
        except Exception:
            pass

    def toggle_overlay_visible(self):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "TOGGLE_OVERLAY_VISIBLE"})
        except Exception:
            pass

    def set_hud_visible(self, visible: bool):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "SET_HUD_VISIBLE", "visible": bool(visible)})
        except Exception:
            pass

    def set_hud_position(self, x, y, normalized: bool=False):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "SET_HUD_POS", "x": x, "y": y, "normalized": bool(normalized)})
        except Exception:
            pass

    def nudge_hud(self, dx: int, dy: int):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "NUDGE_HUD", "dx": int(dx), "dy": int(dy)})
        except Exception:
            pass

    def reset_hud_position(self):
        if not self.enable:
            return
        try:
            self._q.put_nowait({"__cmd": "RESET_HUD_POS"})
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
        """yield hwnd + parent + root ancestor (dedup)"""
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
        """WM_NCHITTEST -> HTTRANSPARENT 강제. (click-through windows only)"""
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

        except Exception as e:
            print("[HUD] _install_httransparent_wndproc failed:", e)

    def _apply_click_through_hwnd(self, hwnd_int: int):
        """click-through 스타일 + HTTRANSPARENT wndproc 설치"""
        for hid in self._iter_related_hwnds(hwnd_int):
            try:
                hwnd = wintypes.HWND(hid)

                ex = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
                ex |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                _set_window_long_ptr(hwnd, GWL_EXSTYLE, ex)

                colorkey = wintypes.COLORREF(0x00FF00FF)  # magenta
                user32.SetLayeredWindowAttributes(hwnd, colorkey, 0, LWA_COLORKEY)

                user32.SetWindowPos(
                    hwnd, wintypes.HWND(0),
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
                )

                self._install_httransparent_wndproc(hid)

            except Exception as e:
                print("[HUD] apply_click_through_hwnd failed:", e)

    def _apply_handle_hwnd(self, hwnd_int: int):
        """
        handle 전용 스타일:
        - transparentcolorkey는 유지
        - WS_EX_TRANSPARENT(클릭스루)만 빼고,
        - NOACTIVATE/TOOLWINDOW는 유지해서 포커스 간섭 최소화
        - WndProc(HTTRANSPARENT)는 절대 설치하지 않음
        """
        for hid in self._iter_related_hwnds(hwnd_int):
            try:
                hwnd = wintypes.HWND(hid)
                ex = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
                ex |= (WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                ex &= ~(WS_EX_TRANSPARENT)  # 클릭 가능
                _set_window_long_ptr(hwnd, GWL_EXSTYLE, ex)

                colorkey = wintypes.COLORREF(0x00FF00FF)  # magenta
                user32.SetLayeredWindowAttributes(hwnd, colorkey, 0, LWA_COLORKEY)

                user32.SetWindowPos(
                    hwnd, wintypes.HWND(0),
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
                )
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

    def _apply_handle_style(self, win: tk.Toplevel):
        try:
            win.update_idletasks()
            win.update()
        except Exception:
            pass
        for w in self._walk_widgets(win):
            try:
                self._apply_handle_hwnd(w.winfo_id())
            except Exception:
                pass

    def _sync_handle_pos(self):
        """HUD 우상단에 handle을 항상 붙임"""
        try:
            if self._handle_win is None or self._hud_win is None:
                return
            x = self._hud_win.winfo_rootx()
            y = self._hud_win.winfo_rooty()
            self._handle_win.geometry(
                f"{self.HANDLE_W}x{self.HANDLE_H}+{x + self.HUD_W - self.HANDLE_W - 12}+{y + 12}"
            )
        except Exception:
            pass

    # -------- bubble text helpers --------
    @staticmethod
    def _pick_first_str(st: dict, keys):
        for k in keys:
            v = st.get(k, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _common_state_label(self, st: dict, locked: bool) -> Optional[str]:
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
        if mode_u == "RUSH":
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

    def _load_reticle_images(self):
        self._ret_imgs = {}
        if HUD_DEBUG:
            print("[HUD] ASSET_DIR =", ASSET_DIR, "RET_S =", self.RET_S, flush=True)

        for mode, fn in RETICLE_PNG.items():
            path = os.path.join(ASSET_DIR, fn)
            if not os.path.exists(path):
                if HUD_DEBUG:
                    print("[HUD] missing:", mode, path, flush=True)
                continue
            try:
                img = tk.PhotoImage(file=path)
                self._ret_imgs[mode] = img
                if HUD_DEBUG:
                    print("[HUD] loaded", mode, path, img.width(), img.height(), flush=True)
            except Exception as e:
                if HUD_DEBUG:
                    print("[HUD] reticle load failed:", mode, path, e, flush=True)

    # -------- tk thread --------
    def _run_tk(self):
        print("[HUD] _run_tk entered", flush=True)
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

        hx, hy = self._clamp_screen_xy(self._hud_x, self._hud_y, self.HUD_W, self.HUD_H)
        self._hud_x, self._hud_y = hx, hy
        hud.geometry(f"{self.HUD_W}x{self.HUD_H}+{hx}+{hy}")

        hud_canvas = tk.Canvas(
            hud, width=self.HUD_W, height=self.HUD_H,
            bd=0, highlightthickness=0, bg=TRANSPARENT
        )
        hud_canvas.pack(fill="both", expand=True)
        self._hud_canvas = hud_canvas

        # Drag handle window (☰) : only this is clickable
        handle = tk.Toplevel(root)
        self._handle_win = handle
        handle.overrideredirect(True)
        handle.attributes("-topmost", True)
        handle.configure(bg=TRANSPARENT)
        try:
            handle.wm_attributes("-transparentcolor", TRANSPARENT)
        except Exception:
            pass

        # handle should be clickable
        try:
            handle.attributes("-disabled", False)
        except Exception:
            pass

        # initial pos attached to HUD
        handle.geometry(
            f"{self.HANDLE_W}x{self.HANDLE_H}+{hx + self.HUD_W - self.HANDLE_W - 12}+{hy + 12}"
        )

        hc = tk.Canvas(handle, width=self.HANDLE_W, height=self.HANDLE_H, bd=0, highlightthickness=0, bg=TRANSPARENT)
        hc.pack(fill="both", expand=True)
        self._handle_canvas = hc

        def _draw_handle(accent_hex: str):
            hc.delete("all")
            hc.create_rectangle(
                0, 0, self.HANDLE_W, self.HANDLE_H,
                fill="#0b1222",
                outline=_hex_dim(accent_hex, 0.75),
                width=2
            )
            for i in range(3):
                y = 8 + i * 6
                hc.create_line(8, y, self.HANDLE_W - 8, y, fill="#E5E7EB", width=2)

        _draw_handle(THEME["DEFAULT"]["accent"])

        def _on_handle_press(e):
            try:
                hx0 = hud.winfo_rootx()
                hy0 = hud.winfo_rooty()
            except Exception:
                hx0, hy0 = self._hud_x, self._hud_y
            self._drag_start = (e.x_root, e.y_root, hx0, hy0)

        def _on_handle_drag(e):
            if not self._drag_start:
                return
            sx, sy, hx0, hy0 = self._drag_start
            nx = hx0 + (e.x_root - sx)
            ny = hy0 + (e.y_root - sy)
            nx, ny = self._clamp_screen_xy(nx, ny, self.HUD_W, self.HUD_H)
            self._hud_x, self._hud_y = nx, ny
            try:
                hud.geometry(f"{self.HUD_W}x{self.HUD_H}+{nx}+{ny}")
            except Exception:
                pass
            self._sync_handle_pos()

        def _on_handle_release(_e):
            self._drag_start = None
            self._sync_handle_pos()

        handle.bind("<ButtonPress-1>", _on_handle_press)
        handle.bind("<B1-Motion>", _on_handle_drag)
        handle.bind("<ButtonRelease-1>", _on_handle_release)

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
        self._load_reticle_images()

        # PNG pre-create for first deiconify
        img0 = self._ret_imgs.get("DEFAULT")
        if img0 is None and self._ret_imgs:
            img0 = next(iter(self._ret_imgs.values()), None)
        if img0 is not None:
            self._ret_img_item = ret_canvas.create_image(
                self.RET_S // 2, self.RET_S // 2,
                image=img0, anchor="center"
            )
            self._ret_img_mode = "DEFAULT"

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

        # Tk 레벨 input disable (handle 제외!)
        for w in (hud, ret, tip):
            try:
                w.attributes("-disabled", True)
            except Exception:
                pass

        # click-through (handle is NOT click-through)
        self._apply_click_through(hud)
        self._apply_click_through(ret)
        self._apply_click_through(tip)

        # handle style (layered + colorkey, but NOT click-through and NOT HTTRANSPARENT wndproc)
        self._apply_handle_style(handle)

        last_t = time.time()

        def _apply_visibility_now():
            if not self._overlay_visible:
                for w in (hud, handle, ret, tip):
                    try:
                        w.withdraw()
                    except Exception:
                        pass
                return

            # overlay on
            if self._hud_panel_visible:
                try: hud.deiconify()
                except Exception: pass
                try: handle.deiconify()
                except Exception: pass
            else:
                try: hud.withdraw()
                except Exception: pass
                try: handle.withdraw()
                except Exception: pass

        def tick():
            nonlocal last_t

            if self._stop.is_set():
                for w in (hud, handle, ret, tip, root):
                    try:
                        if w is not None:
                            w.destroy()
                    except Exception:
                        pass
                return

            latest = None
            stop_cmd = False
            try:
                while True:
                    item = self._q.get_nowait()

                    # command?
                    if isinstance(item, dict) and item.get("__cmd"):
                        cmd = item["__cmd"]

                        if cmd == "STOP":
                            stop_cmd = True
                            break

                        if cmd == "SET_OVERLAY_VISIBLE":
                            self._overlay_visible = bool(item.get("visible", True))
                            _apply_visibility_now()
                            continue

                        if cmd == "TOGGLE_OVERLAY_VISIBLE":
                            self._overlay_visible = not self._overlay_visible
                            _apply_visibility_now()
                            continue

                        if cmd == "SET_HUD_VISIBLE":
                            self._hud_panel_visible = bool(item.get("visible", True))
                            _apply_visibility_now()
                            continue

                        if cmd == "SET_HUD_POS":
                            x = item.get("x", self._hud_x)
                            y = item.get("y", self._hud_y)
                            normalized = bool(item.get("normalized", False))
                            try:
                                if normalized:
                                    self._hud_x = int(self.vx + float(x) * float(self.vw))
                                    self._hud_y = int(self.vy + float(y) * float(self.vh))
                                else:
                                    self._hud_x = int(float(x))
                                    self._hud_y = int(float(y))
                                hx2, hy2 = self._clamp_screen_xy(self._hud_x, self._hud_y, self.HUD_W, self.HUD_H)
                                self._hud_x, self._hud_y = hx2, hy2
                                hud.geometry(f"{self.HUD_W}x{self.HUD_H}+{hx2}+{hy2}")
                                self._sync_handle_pos()
                            except Exception:
                                pass
                            continue

                        if cmd == "NUDGE_HUD":
                            self._hud_x += int(item.get("dx", 0) or 0)
                            self._hud_y += int(item.get("dy", 0) or 0)
                            hx2, hy2 = self._clamp_screen_xy(self._hud_x, self._hud_y, self.HUD_W, self.HUD_H)
                            self._hud_x, self._hud_y = hx2, hy2
                            try:
                                hud.geometry(f"{self.HUD_W}x{self.HUD_H}+{hx2}+{hy2}")
                                self._sync_handle_pos()
                            except Exception:
                                pass
                            continue

                        if cmd == "RESET_HUD_POS":
                            self._hud_x, self._hud_y = 20, 20
                            hx2, hy2 = self._clamp_screen_xy(self._hud_x, self._hud_y, self.HUD_W, self.HUD_H)
                            self._hud_x, self._hud_y = hx2, hy2
                            try:
                                hud.geometry(f"{self.HUD_W}x{self.HUD_H}+{hx2}+{hy2}")
                                self._sync_handle_pos()
                            except Exception:
                                pass
                            continue

                    # normal status
                    latest = item

            except Exception:
                pass

            if stop_cmd:
                self._stop.set()
                root.after(0, tick)
                return

            if isinstance(latest, dict):
                self._latest = latest

            nowt = time.time()
            dt = max(1e-6, nowt - last_t)
            last_t = nowt
            self._phase += dt

            self._render()

            # 주기적 재적용(드물게 풀리는 환경 대비) - handle은 절대 건드리지 않음
            self._ct_tick += 1
            if (self._ct_tick % 60) == 0:
                for w in (hud, ret, tip):
                    self._apply_click_through(w)
                    try:
                        w.attributes("-disabled", True)
                    except Exception:
                        pass

            root.after(16, tick)

        root.after(0, tick)
        try:
            root.mainloop()
        except Exception:
            pass

    def _render(self):
        st = self._latest if isinstance(self._latest, dict) else {}
        mode = _mode_of(st)
        accent = THEME[mode]["accent"]

        # ---- visibility gating (critical) ----
        if not self._overlay_visible:
            for w in (self._hud_win, self._handle_win, self._ret_win, self._tip_win):
                try:
                    if w is not None:
                        w.withdraw()
                except Exception:
                    pass
            return

        # overlay on: hud panel only (ret/tip are controlled below)
        if self._hud_panel_visible:
            try:
                if self._hud_win is not None:
                    self._hud_win.deiconify()
            except Exception:
                pass
            try:
                if self._handle_win is not None:
                    self._handle_win.deiconify()
            except Exception:
                pass
        else:
            for w in (self._hud_win, self._handle_win):
                try:
                    if w is not None:
                        w.withdraw()
                except Exception:
                    pass

        # keep handle attached
        self._sync_handle_pos()

        # update handle drawing only when accent changed
        if self._handle_canvas is not None and self._handle_last_accent != accent:
            self._handle_last_accent = accent
            try:
                hc = self._handle_canvas
                hc.delete("all")
                hc.create_rectangle(
                    0, 0, self.HANDLE_W, self.HANDLE_H,
                    fill="#0b1222",
                    outline=_hex_dim(accent, 0.75),
                    width=2
                )
                for i in range(3):
                    y = 8 + i * 6
                    hc.create_line(8, y, self.HANDLE_W - 8, y, fill="#E5E7EB", width=2)
            except Exception:
                pass

        tracking = bool(st.get("tracking", st.get("isTracking", False)))
        locked = bool(st.get("locked", False))
        gesture = str(st.get("gesture", "NONE"))
        fps = float(st.get("fps", 0.0) or 0.0)
        connected = bool(st.get("connected", True))

        # ---- HUD panel ----
        c = self._hud_canvas
        if c is not None and self._hud_panel_visible:
            c.delete("all")

            bg = "#08101f"
            border = _hex_dim(accent, 0.80)
            fg = "#E5E7EB"
            sub = "#9CA3AF"

            c.create_rectangle(8, 8, self.HUD_W-8, self.HUD_H-8, fill=bg, outline=border, width=2)
            c.create_rectangle(8, 8, 14, self.HUD_H-8, fill=accent, outline="")

            dot = "#22c55e" if connected else "#ef4444"
            c.create_oval(20, 18, 28, 26, fill=dot, outline="")
            c.create_text(34, 22, anchor="w", fill=fg, font=("Segoe UI", 11, "bold"), text=mode)

            # ✅ LOCK/OK pill shifted left so it never overlaps the handle
            pill_text = "LOCK" if locked else "OK"
            pill_fill = "#f59e0b" if locked else _hex_dim(accent, 0.55)

            reserve_right = int(getattr(self, "HANDLE_W", 34)) + 22  # handle 폭 + 여유
            pill_w = 70
            pill_h0, pill_h1 = 14, 34

            pill_x1 = (self.HUD_W - 16) - reserve_right
            pill_x0 = pill_x1 - pill_w

            pill_x0 = max(90, pill_x0)  # safety
            pill_x1 = pill_x0 + pill_w

            c.create_rectangle(pill_x0, pill_h0, pill_x1, pill_h1, fill=pill_fill, outline="")
            c.create_text(
                (pill_x0 + pill_x1) // 2, (pill_h0 + pill_h1) // 2,
                fill="#050a14", font=("Segoe UI", 9, "bold"), text=pill_text
            )

            c.create_text(20, 52, anchor="w", fill=sub, font=("Segoe UI", 9), text=f"GESTURE: {gesture}")
            c.create_text(20, 70, anchor="w", fill=sub, font=("Segoe UI", 9), text=f"TRACK: {'ON' if tracking else 'OFF'}")
            c.create_text(self.HUD_W-20, 70, anchor="e", fill=sub, font=("Segoe UI", 9), text=f"{fps:.1f} FPS")

            base_y = 96
            for i in range(0, 12):
                x = 20 + i * 24
                amp = 6 if tracking else 2
                y = base_y + math.sin(self._phase * 2.2 + i * 0.55) * amp
                c.create_line(x, base_y, x + 18, y, fill=_hex_dim(accent, 0.55), width=2)

        # ---- Reticle / Tip ----
        if self._ret_win is None or self._ret_canvas is None:
            return

        tipw = self._tip_win
        tipc = self._tip_canvas

        # Always follow OS cursor
        osx, osy = self._get_os_cursor_xy()

        # fallback only if cursor can't be read
        if osx is None or osy is None:
            x01, y01 = _normalize_pointer(st.get("pointerX"), st.get("pointerY"), self.vw, self.vh)
            if x01 is None or y01 is None:
                try:
                    self._ret_win.withdraw()
                except Exception:
                    pass
                if tipw is not None:
                    try:
                        tipw.withdraw()
                    except Exception:
                        pass
                return
            osx = self.vx + int(x01 * self.vw)
            osy = self.vy + int(y01 * self.vh)

        # reticle show
        try:
            self._ret_win.deiconify()
        except Exception:
            pass

        if not self._ret_visible:
            self._ret_visible = True

        gx = osx - self.RET_S // 2
        gy = osy - self.RET_S // 2
        gx, gy = self._clamp_screen_xy(gx, gy, self.RET_S, self.RET_S)
        try:
            self._ret_win.geometry(f"{self.RET_S}x{self.RET_S}+{gx}+{gy}")
        except Exception:
            pass

        # PNG reticle
        rc = self._ret_canvas
        key = mode if mode in self._ret_imgs else "DEFAULT"
        img = self._ret_imgs.get(key) or self._ret_imgs.get("DEFAULT")
        if img is None:
            try:
                self._ret_win.withdraw()
            except Exception:
                pass
            if tipw is not None:
                try:
                    tipw.withdraw()
                except Exception:
                    pass
            return

        if self._ret_img_item is None:
            rc.delete("all")
            self._ret_img_item = rc.create_image(self.RET_S // 2, self.RET_S // 2, image=img, anchor="center")
            self._ret_img_mode = key
        elif self._ret_img_mode != key:
            rc.itemconfig(self._ret_img_item, image=img)
            self._ret_img_mode = key

        # ---- Tip bubble ----
        if tipw is None or tipc is None:
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

        px = osx - self.vx
        py = osy - self.vy

        tx = self.vx + px + self.TIP_OX
        ty = self.vy + py + self.TIP_OY
        tx, ty = self._clamp_screen_xy(tx, ty, self.TIP_W, self.TIP_H)
        try:
            tipw.geometry(f"{self.TIP_W}x{self.TIP_H}+{tx}+{ty}")
        except Exception:
            pass

        tipc.delete("all")
        tip_bg = "#0b1222"
        tip_border = _hex_dim(accent, 0.85)
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
