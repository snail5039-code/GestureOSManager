# gestureos_agent/hud_overlay.py
# Windows only: Always-on-top transparent HUD overlay (click-through)
# - Two small windows: HUD (top-left) + Reticle (follows pointer)
# - Apply click-through to: widget hwnd + parent hwnd + root/ancestor hwnd + all descendants
# - Hard fix: WM_NCHITTEST -> HTTRANSPARENT (subclass WndProc)
# - Extra safety: Tk '-disabled' attribute (very effective on Win10/11)

import os
import threading
import queue
import ctypes
from ctypes import wintypes
import tkinter as tk
import time
import math

# ---------------- Win32 constants ----------------
GWL_EXSTYLE = -20
GWL_WNDPROC = -4

WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_NOACTIVATE  = 0x08000000

LWA_COLORKEY = 0x00000001

WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1

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
    color_hex = color_hex.lstrip("#")
    r = int(color_hex[0:2], 16)
    g = int(color_hex[2:4], 16)
    b = int(color_hex[4:6], 16)
    r = int(r * a); g = int(g * a); b = int(b * a)
    return f"#{r:02x}{g:02x}{b:02x}"

# ---- OS cursor fallback (for immediate reticle show) ----
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def _get_os_cursor_norm01(vx, vy, vw, vh):
    """Return OS cursor position normalized to virtual screen (0~1)."""
    try:
        pt = _POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return (None, None)
        x01 = (pt.x - vx) / max(1, vw)
        y01 = (pt.y - vy) / max(1, vh)
        x01 = max(0.0, min(1.0, float(x01)))
        y01 = max(0.0, min(1.0, float(y01)))
        return (x01, y01)
    except Exception:
        return (None, None)

class OverlayHUD:
    """
    Two-window HUD:
      1) HUD panel (top-left)
      2) Reticle window that follows pointer
    Both are click-through.
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
        self._hud_canvas = None
        self._ret_canvas = None

        self.HUD_W, self.HUD_H = 320, 118
        self.RET_S = 48

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

    # -------- internal helpers --------
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
        """
        WM_NCHITTEST -> HTTRANSPARENT 강제.
        """
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
        # IMPORTANT: apply to hwnd + parent + root
        for hid in self._iter_related_hwnds(hwnd_int):
            try:
                hwnd = wintypes.HWND(hid)

                ex = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
                ex |= (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                _set_window_long_ptr(hwnd, GWL_EXSTYLE, ex)

                # magenta (#ff00ff) COLORREF=0x00BBGGRR -> 0x00FF00FF
                colorkey = wintypes.COLORREF(0x00FF00FF)
                user32.SetLayeredWindowAttributes(hwnd, colorkey, 0, LWA_COLORKEY)

                # force refresh
                user32.SetWindowPos(
                    hwnd, wintypes.HWND(0),
                    0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
                )

                # force hit-test transparent
                self._install_httransparent_wndproc(hid)

            except Exception as e:
                print("[HUD] apply_click_through_hwnd failed:", e)

    def _walk_widgets(self, w):
        """recursive widget traversal (Tk가 중간에 더 만들 수 있어서)"""
        yield w
        try:
            for ch in w.winfo_children():
                yield from self._walk_widgets(ch)
        except Exception:
            return

    def _apply_click_through(self, win: tk.Toplevel):
        """Toplevel + all descendants hwnds에 적용"""
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
        hud.geometry(f"{self.HUD_W}x{self.HUD_H}+20+20")

        hud_canvas = tk.Canvas(
            hud, width=self.HUD_W, height=self.HUD_H,
            bd=0, highlightthickness=0, bg=TRANSPARENT
        )
        hud_canvas.pack(fill="both", expand=True)
        self._hud_canvas = hud_canvas

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
        
        # ✅ PNG를 "미리" 하나 만들어두면, 첫 deiconify 때 바로 그려진다
        img0 = self._ret_imgs.get("DEFAULT")
        if img0 is None and self._ret_imgs:
            # DEFAULT가 없으면 아무거나 1개
            img0 = next(iter(self._ret_imgs.values()), None)

        if img0 is not None:
            self._ret_img_item = ret_canvas.create_image(
                self.RET_S // 2, self.RET_S // 2,
                image=img0, anchor="center"
            )
            self._ret_img_mode = "DEFAULT"

        # 추가 안전장치: Tk 레벨에서 input 자체 disable
        # (WS_EX_TRANSPARENT가 환경 따라 완벽하지 않을 때도 이게 거의 해결)
        try:
            hud.attributes("-disabled", True)
        except Exception:
            pass
        try:
            ret.attributes("-disabled", True)
        except Exception:
            pass

        # IMPORTANT: apply to BOTH windows (and all descendants)
        self._apply_click_through(hud)
        self._apply_click_through(ret)

        last_t = time.time()

        def tick():
            nonlocal last_t

            if self._stop.is_set():
                try: hud.destroy()
                except Exception: pass
                try: ret.destroy()
                except Exception: pass
                try: root.destroy()
                except Exception: pass
                return

            latest = None
            stop_cmd = False
            try:
                while True:
                    item = self._q.get_nowait()
                    if isinstance(item, dict) and item.get("__cmd") == "STOP":
                        stop_cmd = True
                        break
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

            # 드물게 풀리는 케이스 대비해서 주기적으로 재적용
            self._ct_tick += 1
            if (self._ct_tick % 60) == 0:
                self._apply_click_through(hud)
                self._apply_click_through(ret)
                try:
                    hud.attributes("-disabled", True)
                    ret.attributes("-disabled", True)
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

        tracking = bool(st.get("tracking", st.get("isTracking", False)))
        locked = bool(st.get("locked", False))
        gesture = str(st.get("gesture", "NONE"))
        fps = float(st.get("fps", 0.0) or 0.0)
        connected = bool(st.get("connected", True))

        # ---- HUD panel ----
        c = self._hud_canvas
        if c is None:
            return
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

        pill_text = "LOCK" if locked else "OK"
        pill_fill = "#f59e0b" if locked else _hex_dim(accent, 0.55)
        c.create_rectangle(self.HUD_W-86, 14, self.HUD_W-16, 34, fill=pill_fill, outline="")
        c.create_text(self.HUD_W-51, 24, fill="#050a14", font=("Segoe UI", 9, "bold"), text=pill_text)

        c.create_text(20, 52, anchor="w", fill=sub, font=("Segoe UI", 9), text=f"GESTURE: {gesture}")
        c.create_text(20, 70, anchor="w", fill=sub, font=("Segoe UI", 9), text=f"TRACK: {'ON' if tracking else 'OFF'}")
        c.create_text(self.HUD_W-20, 70, anchor="e", fill=sub, font=("Segoe UI", 9), text=f"{fps:.1f} FPS")

        base_y = 96
        for i in range(0, 12):
            x = 20 + i * 24
            amp = 6 if tracking else 2
            y = base_y + math.sin(self._phase * 2.2 + i * 0.55) * amp
            c.create_line(x, base_y, x + 18, y, fill=_hex_dim(accent, 0.55), width=2)

        # ---- Reticle ----
        if self._ret_win is None or self._ret_canvas is None:
            return

        nowt = time.time()

        # 1) status pointer로 시도
        x01, y01 = _normalize_pointer(st.get("pointerX"), st.get("pointerY"), self.vw, self.vh)

        # 2) 없으면 OS 커서로 fallback (시작 즉시 표시되게)
        if x01 is None or y01 is None:
            ox, oy = _get_os_cursor_norm01(self.vx, self.vy, self.vw, self.vh)
            if ox is not None and oy is not None:
                x01, y01 = ox, oy

        # 3) 그래도 없으면 마지막 값 grace로 유지
        if x01 is None or y01 is None:
            if (nowt - self._last_ptr_ts) <= self.PTR_GRACE_SEC:
                x01, y01 = self._last_ptr01
            else:
                try: self._ret_win.withdraw()
                except Exception: pass
                return
        else:
            self._last_ptr01 = (x01, y01)
            self._last_ptr_ts = nowt

        # 여기부터는 무조건 표시
        try: self._ret_win.deiconify()
        except Exception:
            pass



        try: self._ret_win.deiconify()
        except Exception:
            pass
        # 처음 다시 보이는 프레임이면 아이템 재생성
        if not self._ret_visible:
            self._ret_visible = True
            self._ret_img_item = None
            try:
                self._ret_canvas.delete("all")
            except Exception:
                pass
        px = int(x01 * self.vw)
        py = int(y01 * self.vh)
        gx = self.vx + px - self.RET_S // 2
        gy = self.vy + py - self.RET_S // 2
        try:
            self._ret_win.geometry(f"{self.RET_S}x{self.RET_S}+{gx}+{gy}")
        except Exception:
            pass

        rc = self._ret_canvas

        # --- PNG reticle (mode based) ---
        key = mode if mode in self._ret_imgs else "DEFAULT"
        img = self._ret_imgs.get(key) or self._ret_imgs.get("DEFAULT")

        if img is not None:
            # 매 프레임 delete하지 말고 item만 유지/교체
            if self._ret_img_item is None:
                rc.delete("all")
                self._ret_img_item = rc.create_image(
                    self.RET_S // 2, self.RET_S // 2,
                    image=img, anchor="center"
                )
                self._ret_img_mode = key
            elif self._ret_img_mode != key:
                rc.itemconfig(self._ret_img_item, image=img)
                self._ret_img_mode = key
            return

        # --- fallback: 기존 도형 레티클 ---
        rc.delete("all")

        acc = _hex_dim(accent, 0.55 if locked else 1.0)
        s = self.RET_S
        cx = s // 2
        cy = s // 2

        ring = 16 + int(2 * math.sin(self._phase * 3.0))
        rc.create_oval(cx-ring, cy-ring, cx+ring, cy+ring, outline=acc, width=2)
        rc.create_oval(cx-3, cy-3, cx+3, cy+3, outline="", fill=acc)
        rc.create_line(cx-28, cy, cx-10, cy, fill=acc, width=2)
        rc.create_line(cx+10, cy, cx+28, cy, fill=acc, width=2)
        rc.create_line(cx, cy-28, cx, cy-10, fill=acc, width=2)
        rc.create_line(cx, cy+10, cx, cy+28, fill=acc, width=2)

