# py/gestureos_agent/agents/hands_agent.py
import os
import time
import ctypes
import subprocess
import math

from typing import Any, List, Optional, Tuple

os.environ.setdefault("GLOG_minloglevel", "2")

import cv2
import mediapipe as mp

from ..config import AgentConfig
from ..timeutil import now
from ..gestures import palm_center, classify_gesture
from ..control import ControlMapper
from ..ws_client import WSClient

# =============================================================================
# Camera optional behavior
# =============================================================================
REQUIRE_CAMERA = os.environ.get("GESTUREOS_REQUIRE_CAMERA", "0").strip() in (
    "1",
    "true",
    "True",
    "YES",
    "yes",
)
CAM_RETRY_SEC = float(os.environ.get("GESTUREOS_CAM_RETRY_SEC", "2.0"))
NO_CAMERA_POLL_SEC = float(os.environ.get("GESTUREOS_NO_CAMERA_POLL_SEC", "0.20"))
NO_CAMERA_STATUS_SEC = float(os.environ.get("GESTUREOS_NO_CAMERA_STATUS_SEC", "0.25"))

# =============================================================================
# SAFE imports for modes (import 실패해도 NameError로 죽지 않게)
# =============================================================================
_MODE_IMPORT_ERRS = []


def _safe_import(path: str, name: str):
    try:
        mod = __import__(path, fromlist=[name])
        return getattr(mod, name)
    except Exception as e:
        _MODE_IMPORT_ERRS.append((f"{path}.{name}", repr(e)))
        return None


# mouse
MouseClickDrag = _safe_import("gestureos_agent.modes.mouse", "MouseClickDrag")
MouseRightClick = _safe_import("gestureos_agent.modes.mouse", "MouseRightClick")
MouseScroll = _safe_import("gestureos_agent.modes.mouse", "MouseScroll")
MouseLockToggle = _safe_import("gestureos_agent.modes.mouse", "MouseLockToggle")

# keyboard / draw / ppt
KeyboardHandler = _safe_import("gestureos_agent.modes.keyboard", "KeyboardHandler")
DrawHandler = _safe_import("gestureos_agent.modes.draw", "DrawHandler")
PresentationHandler = _safe_import("gestureos_agent.modes.presentation", "PresentationHandler")

# ui menu / rush
UIModeMenu = _safe_import("gestureos_agent.modes.ui_menu", "UIModeMenu")
RushLRPicker = _safe_import("gestureos_agent.modes.rush_lr", "RushLRPicker")
ColorStickTracker = _safe_import("gestureos_agent.modes.rush_color", "ColorStickTracker")

from ..bindings import DEFAULT_SETTINGS, deep_copy, merge_settings, get_binding
from ..learner_mlp import MLPLearner
from collections import deque, Counter


# =============================================================================
# OS cursor helpers
# =============================================================================
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _get_os_cursor_norm01():
    """Return (x01,y01) normalized to Windows virtual screen (multi-monitor).
    Returns (None,None) if not available."""
    if os.name != "nt":
        return (None, None)
    try:
        user32 = ctypes.windll.user32
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79

        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        pt = _POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return (None, None)

        x01 = (pt.x - vx) / max(1, vw)
        y01 = (pt.y - vy) / max(1, vh)

        x01 = 0.0 if x01 < 0.0 else (1.0 if x01 > 1.0 else float(x01))
        y01 = 0.0 if y01 < 0.0 else (1.0 if y01 > 1.0 else float(y01))
        return (x01, y01)
    except Exception:
        return (None, None)


def _get_os_cursor_xy():
    if os.name != "nt":
        return (None, None)
    try:
        user32 = ctypes.windll.user32
        pt = _POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return (None, None)
        return (int(pt.x), int(pt.y))
    except Exception:
        return (None, None)


# -----------------------------------------------------------------------------
# ✅ Win11 안정형 좌클릭 주입 (VKEY/KEYBOARD에서 PINCH로 OSK 버튼 누르기)
# -----------------------------------------------------------------------------
_IS_WIN = (os.name == "nt")
if _IS_WIN:
    from ctypes import wintypes

    # ✅ 일부 Python에서 wintypes.ULONG_PTR 없음 → 직접 정의
    try:
        ULONG_PTR = wintypes.ULONG_PTR
    except AttributeError:
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32
    INPUT_MOUSE = 0
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    def _win_left_click():
        user32 = ctypes.windll.user32
        down = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)))
        up = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)))
        arr = (_INPUT * 2)(down, up)
        user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(_INPUT))


# tracking loss handling
LOSS_GRACE_SEC = 0.30
HARD_LOSS_SEC = 0.55
REACQUIRE_BLOCK_SEC = 0.12

# NEXT_MODE event (locked + both OPEN_PALM hold)
MODE_HOLD_SEC = 0.8
MODE_COOLDOWN_SEC = 1.2

# =============================================================================
# Mode Palette (OS overlay menu)
# =============================================================================
PALETTE_OPEN_HOLD = 0.35
PALETTE_CONFIRM_HOLD = 0.18
PALETTE_CANCEL_HOLD = 0.45

PALETTE_MAP = {
    "MOUSE": "MOUSE",
    "KEYBOARD": "KEYBOARD",
    "VKEY": "VKEY",
    "DRAW": "DRAW",
    "PRESENTATION": "PRESENTATION",
    "PPT": "PRESENTATION",
    "PAINT": "DRAW",
    "OTHER": "MOUSE",
}

# =============================================================================
# OSK toggle gesture (VKEY only)
# =============================================================================
OSK_TOGGLE_HOLD_SEC = 0.4
OSK_TOGGLE_COOLDOWN_SEC = 0.6

# =============================================================================
# UI LOCK toggle gesture (global)
# =============================================================================
UI_LOCK_HOLD_SEC = 8.0
UI_LOCK_COOLDOWN_SEC = 1.0

# =============================================================================
# ✅ APP START/STOP gesture (global)
# - OPEN_PALM은 이동이랑 충돌 -> 사용 금지
# - 정지 상태 Start: 양손 V_SIGN 홀드
# - 실행 상태 Stop: 양손 FIST 홀드
# =============================================================================
APP_START_HOLD_SEC = 0.9
APP_STOP_HOLD_SEC = 0.9
APP_CMD_COOLDOWN_SEC = 1.5


def _lm_to_payload(lm):
    if lm is None:
        return []
    return [{"x": float(p[0]), "y": float(p[1]), "z": float(p[2])} for p in lm]


def _pinch_thresh_from_ratio(lm, ratio: float, fallback: float = 0.06) -> float:
    try:
        if lm is None or len(lm) != 21:
            return float(fallback)
        x0, y0, _ = lm[0]
        x9, y9, _ = lm[9]
        palm = math.sqrt((x0 - x9) ** 2 + (y0 - y9) ** 2)
        if palm < 1e-6:
            return float(fallback)
        return float(max(0.01, min(0.20, ratio * palm)))
    except Exception:
        return float(fallback)


def _pack_xy(p: Optional[dict]):
    """accept both (cx,cy) or (nx,ny) packs"""
    if p is None:
        return None
    cx = p.get("cx", p.get("nx"))
    cy = p.get("cy", p.get("ny"))
    if cx is None or cy is None:
        return None
    return float(cx), float(cy)


# =============================================================================
# OSK robust helpers (Win+Ctrl+O + tasklist verification)
# =============================================================================
def _tasklist_has(exe_name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        exe = str(exe_name)
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        out = (r.stdout or "").lower()
        return exe.lower() in out
    except Exception:
        return False


def _send_win_ctrl_o():
    """
    Win + Ctrl + O : Windows 내장 'On-Screen Keyboard' 토글 단축키.
    환경/권한 영향이 가장 적어서 OSK 안 뜨는 문제의 마지막 안전망.
    """
    if os.name != "nt":
        return False

    user32 = ctypes.windll.user32

    VK_LWIN = 0x5B
    VK_CONTROL = 0x11
    VK_O = 0x4F

    KEYEVENTF_KEYUP = 0x0002

    try:
        # down
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_O, 0, 0, 0)
        time.sleep(0.02)
        # up
        user32.keybd_event(VK_O, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        return False


class HandsAgent:
    """
    Main agent:
    - MOUSE / KEYBOARD / PRESENTATION / DRAW / VKEY
    - RUSH_HAND: mediapipe hands-based left/right (RushLRPicker)
    - RUSH_COLOR: HSV stick tracking left/right (ColorStickTracker)

    NOTE:
    - VKEY 모드는 "윈도우 OSK/TabTip 띄우기"만 담당.
      (커서 이동/클릭은 hands_agent에서 그대로 처리)
    """

    def __init__(self, cfg: AgentConfig):
        self._request_close_preview = False
        self.cfg = cfg

        # ✅ UI 잠금(프론트 토글) : enabled는 유지하되 제스처 inject만 막는다
        self.ui_locked = False

        if _MODE_IMPORT_ERRS:
            print("[MODE_IMPORT_ERRS]", _MODE_IMPORT_ERRS, flush=True)

        self.enabled = bool(getattr(cfg, "start_enabled", False))

        # ---- initial mode ----
        self.mode = "MOUSE"
        if getattr(cfg, "start_keyboard", False):
            self.mode = "KEYBOARD"
        elif getattr(cfg, "start_rush", False):
            ri = str(getattr(cfg, "rush_input", "HAND")).upper()
            self.mode = "RUSH_COLOR" if ri == "COLOR" else "RUSH_HAND"
        elif getattr(cfg, "start_vkey", False):
            self.mode = "VKEY"

        # lock policy (gesture lock)
        self.locked = True
        if self.enabled:
            self.locked = False
        if self.mode in ("KEYBOARD", "PRESENTATION", "DRAW", "RUSH_HAND", "RUSH_COLOR", "VKEY"):
            self.locked = False

        self.preview = (not getattr(cfg, "headless", False))

        # ✅ 기본: 오른손이 주손(커서손)
        self.cursor_hand_label = "Left" if getattr(cfg, "force_cursor_left", False) else "Right"
        print(
            "[CFG] force_cursor_left=",
            getattr(cfg, "force_cursor_left", None),
            "cursor_hand_label=",
            self.cursor_hand_label,
            flush=True,
        )

        self.control = ControlMapper(
            control_box=getattr(cfg, "control_box", (0.3, 0.35, 0.7, 0.92)),
            gain=float(getattr(cfg, "control_gain", 1.35)),
            ema_alpha=float(getattr(cfg, "ema_alpha", 0.45)),
            deadzone_px=float(getattr(cfg, "deadzone_px", 2.0)),
            move_interval_sec=(1.0 / max(1e-6, float(getattr(cfg, "move_hz", 60.0)))),
        )

        # mode handlers (None guard)
        self.mouse_click = MouseClickDrag() if MouseClickDrag else None
        self.mouse_right = MouseRightClick() if MouseRightClick else None
        self.mouse_scroll = MouseScroll() if MouseScroll else None
        self.mouse_lock = MouseLockToggle() if MouseLockToggle else None

        self.kb = KeyboardHandler() if KeyboardHandler else None
        self.draw = DrawHandler() if DrawHandler else None
        self.ppt = PresentationHandler() if PresentationHandler else None

        self.ui_menu = UIModeMenu() if UIModeMenu else None

        # ---- user settings (gesture bindings) ----
        self.settings: dict = deep_copy(DEFAULT_SETTINGS)

        # rush handlers
        self.rush_lr = RushLRPicker() if RushLRPicker else None
        self.rush_color = (
            ColorStickTracker(
                s_min=int(os.getenv("RUSH_COLOR_S_MIN", "60")),
                v_min=int(os.getenv("RUSH_COLOR_V_MIN", "60")),
                min_area=int(os.getenv("RUSH_COLOR_MIN_AREA", "220")),
                use_bgr_fallback=(os.getenv("RUSH_COLOR_BGR_FALLBACK", "1") == "1"),
                flip_mirror=(os.getenv("RUSH_COLOR_FLIP", "0") == "1"),
                debug=(os.getenv("RUSH_COLOR_DEBUG", "0") == "1"),
            )
            if ColorStickTracker
            else None
        )

        # tracking loss
        self.last_seen_ts = 0.0
        self.last_cursor_lm = None
        self.last_cursor_cxcy = None
        self.last_cursor_gesture = "NONE"
        self.reacquire_until = 0.0

        # NEXT_MODE hold
        self.mode_hold_start = None
        self.last_mode_event_ts = 0.0

        # ---- Palette modal state ----
        self.palette_active = False
        self.palette_open_start = None
        self.palette_confirm_start = None
        self.palette_cancel_start = None

        # HUD tip bubble override
        self.cursor_bubble = None

        # preview window
        self.window_open = False
        # ✅ Win11: HUD 초기 표시가 안 뜨는 케이스 대비 (첫 STATUS 이후 1회 리프레시)
        self._hud_bootstrap_done = False
        self._hud_bootstrap_t0 = time.time()

        # ---- command timing guards ----
        # 일부 UI/상태 동기화 타이밍에서 SET_MODE 직후 DISABLE이 연달아 오는 케이스가 있어
        # KEYBOARD 모드 입력 파이프라인이 바로 꺼지는 문제를 디버깅/완화하기 위한 가드.
        self._last_set_mode_ts = 0.0
        self._disable_guard_sec = float(os.getenv("GESTUREOS_DISABLE_GUARD_SEC", "0.8"))
        self._disable_guard = os.getenv("GESTUREOS_DISABLE_GUARD", "1").strip() in ("1", "true", "True", "YES", "yes")
        self._kb_dbg_last_ts = 0.0

        # ---- OSK state ----
        self.osk_open = False
        self._osk_proc = None  # ✅ 내가 띄운 osk pid 추적(가능한 경우)
        self.osk_toggle_hold_start = None
        self.last_osk_toggle_ts = 0.0

        # ---- UI lock toggle state (FIST hold) ----
        self.ui_lock_hold_start = None
        self.last_ui_lock_toggle_ts = 0.0

        # ✅✅ APP start/stop state
        self.app_start_hold_start = None
        self.app_stop_hold_start = None
        self.last_app_cmd_ts = 0.0

        # 팔레트 열기 직전 OSK 상태 저장(“열려있었으면 닫고, 닫힐 때 복구”)
        self.palette_prev_osk_open = False

        # mediapipe hands
        self.mp_hands = mp.solutions.hands

        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        # learner (personalized MLP)
        self.learner = MLPLearner()

        self._learn_profile_by_mode = (os.getenv("LEARN_PROFILE_BY_MODE", "0") == "1")
        self._mode_profile_map = {
            "MOUSE": "mouse",
            "KEYBOARD": "keyboard",
            "PRESENTATION": "ppt",
            "DRAW": "draw",
            "VKEY": "vkey",
            "RUSH_HAND": "rush",
            "RUSH_COLOR": "rush",
        }

        self.pred_hist = {
            "cursor": deque(maxlen=5),
            "other": deque(maxlen=5),
        }

        # ✅✅ pinch debounce / hysteresis (cursor hand)
        self._pinch_down = False
        self._pinch_t0 = 0.0  # pinch candidate start time
        self._pinch_hold_ms = 90  # tweakable: 70~140ms
        self._pinch_hys_on = 1.00  # ON threshold multiplier (tight)
        self._pinch_hys_off = 1.25  # OFF threshold multiplier (looser)

        # ✅ VKEY/KEYBOARD 강제 클릭(핀치) 엣지 감지
        self._vkey_prev_pinch = False
        self._vkey_last_click_ts = 0.0
        self._vkey_click_cd = 0.28  # 과다 클릭 방지

        # ws
        self.ws = WSClient(
            getattr(cfg, "ws_url", "ws://127.0.0.1:8080/ws/agent"),
            self._on_command,
            enabled=(not getattr(cfg, "no_ws", False)),
        )

        # ---- camera state (optional) ----
        self._cap = None
        self._cam_ok = False
        self._cam_err = ""
        self._cam_last_try_wall = 0.0
        self._last_nocam_status_wall = 0.0

        # boot: start_vkey면 바로 OSK 띄우기
        if str(self.mode).upper() == "VKEY":
            self._enter_vkey_mode()

    # -------------------------------------------------------------------------
    # OSK helpers
    # -------------------------------------------------------------------------
    def _osk_open(self):
        """
        배포 안정형(강화):
        - 우선순위:
          0) Win+Ctrl+O 토글(권한/환경 영향 적음)
          1) ms-inputapp: (Win11 터치 키보드)
          2) TabTip.exe start 실행
          3) osk.exe 직접 실행
        - 실행 후 tasklist로 실제 떠있는지 확인해 self.osk_open을 더 정확히 세팅
        """
        if os.name != "nt":
            return
        if self.osk_open:
            return

        self._osk_proc = None
        launched = False

        # 0) 단축키 토글
        try:
            if _send_win_ctrl_o():
                time.sleep(0.12)
                if _tasklist_has("osk.exe"):
                    launched = True
                    print("[VKEY] toggled OSK via Win+Ctrl+O", flush=True)
        except Exception as e:
            print("[VKEY] hotkey toggle failed:", repr(e), flush=True)

        # 1) Win11 터치키보드 URI
        if not launched:
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "", "ms-inputapp:"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.12)
                if _tasklist_has("TabTip.exe"):
                    launched = True
                print("[VKEY] launched ms-inputapp:", flush=True)
            except Exception as e:
                print("[VKEY] ms-inputapp failed:", repr(e), flush=True)

        # 2) TabTip
        if not launched:
            tabtip = r"C:\Program Files\Common Files\Microsoft Shared\ink\TabTip.exe"
            try:
                if os.path.exists(tabtip):
                    subprocess.Popen(
                        ["cmd", "/c", "start", "", tabtip],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    time.sleep(0.12)
                    if _tasklist_has("TabTip.exe"):
                        launched = True
                    print("[VKEY] launched TabTip via start", flush=True)
            except Exception as e:
                print("[VKEY] TabTip(start) failed:", repr(e), flush=True)

        # 3) osk.exe 직접
        if not launched:
            try:
                p = subprocess.Popen(
                    ["osk.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
                self._osk_proc = p
                time.sleep(0.12)
                if _tasklist_has("osk.exe"):
                    launched = True
                print("[VKEY] launched osk.exe (pid=%s)" % getattr(p, "pid", None), flush=True)
            except Exception as e:
                print("[VKEY] osk.exe failed:", repr(e), flush=True)

        self.osk_open = bool(launched)

    def _osk_close(self):
        if os.name != "nt":
            return

        try:
            if _tasklist_has("osk.exe"):
                _send_win_ctrl_o()
                time.sleep(0.10)
        except Exception:
            pass

        pid = 0
        try:
            pid = int(getattr(self._osk_proc, "pid", 0) or 0) if self._osk_proc else 0
        except Exception:
            pid = 0

        if pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

        for exe in ("osk.exe", "TabTip.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/IM", exe, "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

        self._osk_proc = None
        self.osk_open = False

    def _osk_toggle(self):
        if os.name == "nt" and _tasklist_has("osk.exe"):
            self.osk_open = True
        if self.osk_open:
            self._osk_close()
        else:
            self._osk_open()

    # -------------------------------------------------------------------------
    # WS helpers
    # -------------------------------------------------------------------------
    def send_event(self, name: str, payload: Optional[dict]):
        msg = {"type": "EVENT", "name": name}
        if payload is not None:
            msg["payload"] = payload
        self.ws.send_dict(msg)

    def _force_hide_menu(self):
        """모드 변경/disable 시 라디얼이 남는 문제 방지: 강제 hide + 상태 리셋"""
        hud = getattr(self.cfg, "hud", None)
        if hud:
            try:
                hud.hide_menu()
            except Exception:
                pass
        self.palette_active = False
        self.palette_open_start = None
        self.palette_confirm_start = None
        self.palette_cancel_start = None

    def _on_command(self, data: dict):
        typ = data.get("type")

        if typ in (
            "SET_MODE",
            "ENABLE",
            "DISABLE",
            "SET_PREVIEW",
            "UPDATE_SETTINGS",
            "SET_LOCK",
            "SET_LOCKED",
            "LOCK",
            "UNLOCK",
            "TRAIN_CAPTURE",
            "TRAIN_TRAIN",
            "TRAIN_ENABLE",
            "TRAIN_RESET",
            "TRAIN_SET_PROFILE",
            "TRAIN_PROFILE_CREATE",
            "TRAIN_PROFILE_DELETE",
            "TRAIN_PROFILE_RENAME",
        ):
            print("[PY] cmd:", data, flush=True)

        if typ == "ENABLE":
            self.enabled = True
            self.locked = False

        elif typ == "DISABLE":
            # ✅ KEYBOARD 모드에서 SET_MODE 직후 들어오는 DISABLE(동기화 레이스)로
            # 입력 파이프라인이 바로 꺼지는 케이스가 있어 가드(기본 ON).
            if (
                getattr(self, "_disable_guard", False)
                and str(getattr(self, "mode", "")).upper() == "KEYBOARD"
            ):
                try:
                    dt = time.time() - float(getattr(self, "_last_set_mode_ts", 0.0))
                except Exception:
                    dt = 999.0
                if dt <= float(getattr(self, "_disable_guard_sec", 0.8)):
                    print(f"[PY] IGNORE DISABLE (guard {dt:.3f}s after SET_MODE)", flush=True)
                    return

            self.enabled = False
            self._reset_side_effects()
            self._osk_close()
            self._force_hide_menu()

        elif typ == "SET_LOCK" or typ == "SET_LOCKED":
            v = data.get("enabled", data.get("locked", True))
            self.ui_locked = bool(v)

            if self.ui_locked:
                self._reset_side_effects()
                self._force_hide_menu()

        elif typ == "LOCK":
            self.ui_locked = True
            self._reset_side_effects()
            self._force_hide_menu()

        elif typ == "UNLOCK":
            self.ui_locked = False

        elif typ == "SET_MODE":
            new_mode = str(data.get("mode", "MOUSE")).upper()
            self.apply_set_mode(new_mode)

        elif typ == "SET_PREVIEW":
            enabled = bool(data.get("enabled", True))
            self.preview = enabled
            print(f"[PY] preview set -> {enabled} (window_open={self.window_open})", flush=True)
            if not enabled:
                self._request_close_preview = True

        elif typ == "UPDATE_SETTINGS":
            incoming = data.get("settings") or {}
            self.apply_settings(incoming)

        elif typ == "TRAIN_CAPTURE":
            p = data.get("payload") or {}
            hand = str(p.get("hand", "cursor"))
            label = str(p.get("label", "OPEN_PALM"))
            seconds = float(p.get("seconds", 2.0))
            hz = int(p.get("hz", 15))
            self.learner.start_capture(hand=hand, label=label, seconds=seconds, hz=hz)

        elif typ == "TRAIN_TRAIN":
            self.learner.train()

        elif typ == "TRAIN_ENABLE":
            self.learner.enabled = bool(data.get("enabled", True))
            self.learner.save()

        elif typ == "TRAIN_RESET":
            self.learner.reset()

        elif typ == "TRAIN_ROLLBACK":
            self.learner.rollback()

        elif typ == "TRAIN_SET_PROFILE":
            p = data.get("payload") or {}
            name = p.get("profile") or data.get("profile") or data.get("name") or "default"
            self.learner.set_profile(str(name))
            self.learner.save()

        elif typ == "TRAIN_PROFILE_CREATE":
            p = data.get("payload") or {}
            name = p.get("profile") or "new"
            copy = bool(p.get("copy", True))
            self.learner.create_profile(str(name), copy_from_current=copy, switch=True)

        elif typ == "TRAIN_PROFILE_DELETE":
            p = data.get("payload") or {}
            name = p.get("profile") or data.get("profile") or data.get("name")
            if name:
                self.learner.delete_profile(str(name))

        elif typ == "TRAIN_PROFILE_RENAME":
            p = data.get("payload") or {}
            src = p.get("from") or p.get("src")
            dst = p.get("to") or p.get("dst")
            if src and dst:
                self.learner.rename_profile(str(src), str(dst))

    # ---------- mode + state ----------
    def _reset_side_effects(self):
        if self.mouse_click:
            self.mouse_click.reset()
        if self.mouse_right:
            self.mouse_right.reset()
        if self.mouse_scroll:
            self.mouse_scroll.reset()

        if self.kb:
            self.kb.reset()
        if self.draw:
            self.draw.reset()
        if self.ppt:
            self.ppt.reset()

    def _apply_ui_locked_side_effects(self):
        self._reset_side_effects()
        self._force_hide_menu()

    def apply_settings(self, incoming: dict):
        try:
            self.settings = merge_settings(self.settings, incoming)
            print("[PY] apply_settings -> version", self.settings.get("version"), flush=True)

            g = None
            if isinstance(incoming, dict):
                g = incoming.get("control_gain", None)
                if g is None:
                    g = incoming.get("gain", None)
                if g is None:
                    g = incoming.get("controlGain", None)

            if g is not None:
                try:
                    g = float(g)
                    g = max(0.2, min(4.0, g))
                    if hasattr(self.control, "set_gain") and callable(getattr(self.control, "set_gain")):
                        self.control.set_gain(g)
                    else:
                        setattr(self.control, "gain", g)
                    print(f"[PY] control_gain applied -> {g}", flush=True)
                except Exception as e:
                    print("[PY] control_gain apply failed:", repr(e), flush=True)

        except Exception as e:
            print("[PY] apply_settings failed:", e, flush=True)

    # ---------- VKEY helpers ----------
    def _enter_vkey_mode(self):
        if self.kb and hasattr(self.kb, "on_enter"):
            try:
                self.kb.on_enter(mode="VKEY")
            except TypeError:
                try:
                    self.kb.on_enter("VKEY")
                except Exception:
                    pass
            except Exception:
                pass

        self._osk_open()

    def apply_set_mode(self, new_mode: str):
        """
        ✅ 강제 정책:
        - 모드 바뀌는 순간 라디얼(모드창) 무조건 숨김 (남는 현상 방지)
        - VKEY -> 다른 모드면 OSK 무조건 닫기
        - 다른 모드 -> VKEY면 OSK 오픈
        """
        prev_mode = str(self.mode).upper()

        nm = str(new_mode).upper()
        if nm == "PPT":
            nm = "PRESENTATION"
        if nm == "PAINT":
            nm = "DRAW"
        if nm == "RUSH":
            nm = "RUSH_HAND"
        if nm in ("RUSH_STICK", "RUSH_COLOR_STICK"):
            nm = "RUSH_COLOR"

        allowed = {"MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "VKEY", "RUSH_HAND", "RUSH_COLOR"}
        if nm not in allowed:
            print("[PY] apply_set_mode ignored:", new_mode, flush=True)
            return

        self._force_hide_menu()

        if prev_mode == "VKEY" and nm != "VKEY":
            self._osk_close()

        self.control.reset_ema()

        if self.mode == "DRAW" and nm != "DRAW":
            if self.draw:
                self.draw.reset()

        if nm != "MOUSE":
            if self.mouse_click:
                self.mouse_click.reset()
            if self.mouse_right:
                self.mouse_right.reset()
            if self.mouse_scroll:
                self.mouse_scroll.reset()

        if nm in ("PRESENTATION", "DRAW", "RUSH_HAND", "RUSH_COLOR", "VKEY"):
            self.locked = False

        if self.kb:
            self.kb.reset()
        if self.ppt:
            self.ppt.reset()
        if self.draw:
            self.draw.reset()

        self.mode = nm

        if self._learn_profile_by_mode:
            cur_p = str(getattr(self.learner, "profile", "default"))
            if "__" not in cur_p:
                try:
                    self.learner.set_profile(self._mode_profile_map.get(str(self.mode).upper(), "default"))
                except Exception:
                    pass

        print("[PY] apply_set_mode ->", self.mode, flush=True)
        try:
            self._last_set_mode_ts = time.time()
        except Exception:
            self._last_set_mode_ts = 0.0

        if nm == "VKEY":
            self._enter_vkey_mode()

    # -------------------------------------------------------------------------
    # capture
    # -------------------------------------------------------------------------
    def _open_camera(self):
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        except Exception:
            cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            raise RuntimeError("webcam open failed")

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap

    def _close_camera(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self._cam_ok = False

    def _try_open_camera(self) -> bool:
        self._cam_last_try_wall = time.time()
        try:
            self._cap = self._open_camera()
            self._cam_ok = True
            self._cam_err = ""
            print("[PY] camera opened", flush=True)
            return True
        except Exception as e:
            self._cap = None
            self._cam_ok = False
            self._cam_err = f"{type(e).__name__}: {e}"
            print("[PY] camera not available:", self._cam_err, flush=True)
            return False

    def _send_status_no_camera(self, fps: float = 0.0):
        self.cursor_bubble = f"NO CAMERA • retry {CAM_RETRY_SEC:.1f}s"
        self._send_status(
            fps=float(fps),
            cursor_gesture="NONE",
            other_gesture="NONE",
            scroll_active=False,
            can_mouse=False,
            can_key=False,
            rush_left=None,
            rush_right=None,
            cursor_lm=None,
            other_lm=None,
            cursor_cx=0.5,
            cursor_cy=0.5,
            got_cursor=False,
        )

    # -------------------------------------------------------------------------
    # palette modal
    # -------------------------------------------------------------------------
    def _update_pinch_state(self, is_pinch_rule: bool, now_s: float) -> bool:
        hold_s = self._pinch_hold_ms / 1000.0

        if not self._pinch_down:
            if is_pinch_rule:
                if self._pinch_t0 <= 0.0:
                    self._pinch_t0 = now_s
                if (now_s - self._pinch_t0) >= hold_s:
                    self._pinch_down = True
                    self._pinch_t0 = 0.0
            else:
                self._pinch_t0 = 0.0
        else:
            if not is_pinch_rule:
                if self._pinch_t0 <= 0.0:
                    self._pinch_t0 = now_s
                if (now_s - self._pinch_t0) >= 0.06:
                    self._pinch_down = False
                    self._pinch_t0 = 0.0
            else:
                self._pinch_t0 = 0.0

        return self._pinch_down

    def _update_palette_modal(
        self,
        t: float,
        got_cursor: bool,
        got_other: bool,
        cursor_gesture: str,
        other_gesture: str,
        cursor_cx: float,
        cursor_cy: float,
    ) -> bool:
        """Returns True if palette is active (and normal mode side-effects must be blocked)."""
        self.cursor_bubble = None
        hud = getattr(self.cfg, "hud", None)

        if not hud:
            self._force_hide_menu()
            return False

        # open trigger
        if (
            (not self.palette_active)
            and self.enabled
            and got_other
            and (cursor_gesture == "V_SIGN")
            and (other_gesture == "V_SIGN")
        ):
            if self.palette_open_start is None:
                self.palette_open_start = t

            if (t - self.palette_open_start) >= PALETTE_OPEN_HOLD:
                self.palette_prev_osk_open = bool(self.osk_open)
                if self.palette_prev_osk_open:
                    self._osk_close()

                self.palette_active = True
                self.palette_open_start = None
                self.palette_confirm_start = None
                self.palette_cancel_start = None

                cx, cy = _get_os_cursor_xy()
                if cx is not None and cy is not None:
                    hud.show_menu(center_xy=(cx, cy))
                else:
                    hud.show_menu()

                self._reset_side_effects()
        else:
            self.palette_open_start = None

        if not self.palette_active:
            return False

        hover = hud.get_menu_hover()
        self.cursor_bubble = f"MENU • {hover or '...'} (PINCH=확정, FIST=취소)"

        no_inject = bool(getattr(self.cfg, "no_inject", False))
        if (not no_inject) and (t >= self.reacquire_until) and got_cursor and (cursor_gesture == "OPEN_PALM"):
            ux, uy = self.control.map_control_to_screen(cursor_cx, cursor_cy)
            ex, ey = self.control.apply_ema(ux, uy)
            self.control.move_cursor(ex, ey, t)

        if (cursor_gesture == "PINCH_INDEX") and hover:
            if self.palette_confirm_start is None:
                self.palette_confirm_start = t
            if (t - self.palette_confirm_start) >= PALETTE_CONFIRM_HOLD:
                picked = PALETTE_MAP.get(str(hover).upper(), "MOUSE")

                self.apply_set_mode(picked)

                try:
                    hud.hide_menu()
                except Exception:
                    pass
                self.palette_active = False
                self.palette_confirm_start = None
                self.palette_cancel_start = None
                self._reset_side_effects()

                if str(self.mode).upper() == "VKEY" and self.palette_prev_osk_open:
                    self._osk_open()
                self.palette_prev_osk_open = False
        else:
            self.palette_confirm_start = None

        if cursor_gesture == "FIST":
            if self.palette_cancel_start is None:
                self.palette_cancel_start = t
            if (t - self.palette_cancel_start) >= PALETTE_CANCEL_HOLD:
                try:
                    hud.hide_menu()
                except Exception:
                    pass
                self.palette_active = False
                self.palette_confirm_start = None
                self.palette_cancel_start = None
                self._reset_side_effects()

                if str(self.mode).upper() == "VKEY" and self.palette_prev_osk_open:
                    self._osk_open()
                self.palette_prev_osk_open = False
        else:
            self.palette_cancel_start = None

        return bool(self.palette_active)

    # -------------------------------------------------------------------------
    # main loop helpers
    # -------------------------------------------------------------------------
    def _smooth_pred(self, hand: str, pred, score: float, rule: str):
        if pred is None:
            self.pred_hist[hand].append(("NONE", 0.0))
        else:
            self.pred_hist[hand].append((str(pred), float(score)))

        labels = [p for (p, _) in self.pred_hist[hand] if p and p != "NONE"]
        if not labels:
            return (None, 0.0)

        lab, cnt = Counter(labels).most_common(1)[0]
        if cnt < 3:
            return (None, 0.0)

        scores = [s for (p, s) in self.pred_hist[hand] if p == lab]
        avg = (sum(scores) / len(scores)) if scores else 0.0

        if lab == "PINCH_INDEX" and rule != "PINCH_INDEX":
            return (None, avg)

        return (lab, avg)

    # -------------------------------------------------------------------------
    # main loop
    # -------------------------------------------------------------------------
    def run(self):
        print("[PY] running:", os.path.abspath(__file__), flush=True)
        print(
            "[PY] WS_URL:",
            getattr(self.cfg, "ws_url", ""),
            "(disabled)" if getattr(self.cfg, "no_ws", False) else "",
            flush=True,
        )

        self.ws.start()
        self._try_open_camera()

        if REQUIRE_CAMERA and (self._cap is None):
            print("[PY] REQUIRE_CAMERA=1 but camera open failed -> exit", flush=True)
            self._send_status_no_camera(fps=0.0)
            return

        prev_t = now()
        fps = 0.0

        while True:
            # ==========================
            # NO CAMERA mode (keep alive)
            # ==========================
            if self._cap is None:
                wall = time.time()

                if self.window_open:
                    try:
                        cv2.destroyWindow("GestureOS Agent")
                    except Exception:
                        try:
                            cv2.destroyAllWindows()
                        except Exception:
                            pass
                    self.window_open = False
                    self._request_close_preview = False

                if (wall - self._last_nocam_status_wall) >= NO_CAMERA_STATUS_SEC:
                    self._last_nocam_status_wall = wall
                    self._send_status_no_camera(fps=0.0)

                if (wall - self._cam_last_try_wall) >= CAM_RETRY_SEC:
                    self._try_open_camera()

                time.sleep(max(0.01, NO_CAMERA_POLL_SEC))
                continue

            # ==========================
            # CAMERA OK mode
            # ==========================
            ok, frame = self._cap.read()
            if not ok or frame is None:
                self._cam_ok = False
                self._cam_err = "camera_read_failed"
                self._close_camera()
                continue

            frame = cv2.flip(frame, 1)  # mirror
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            t = now()
            dt = max(t - prev_t, 1e-6)
            prev_t = t
            fps = 0.9 * fps + 0.1 * (1.0 / dt)

            res = self.hands.process(rgb)

            # NOTE: frame is mirrored (cv2.flip(frame, 1)). MediaPipe handedness labels
            # must be swapped to match the user's physical left/right.
            MIRROR_MODE = False

            # hands_list keeps the legacy shape: [(label, lm), ...] for downstream modules
            hands_list: List[Tuple[Optional[str], Any]] = []
            # hands_meta: richer info for reliable main/aux hand selection
            hands_meta: List[dict] = []

            if res.multi_hand_landmarks:
                labels: List[Optional[str]] = []
                scores: List[float] = []

                if res.multi_handedness:
                    for h in res.multi_handedness:
                        cls = h.classification[0]
                        labels.append(getattr(cls, "label", None))
                        try:
                            scores.append(float(getattr(cls, "score", 0.0)))
                        except Exception:
                            scores.append(0.0)
                else:
                    labels = [None] * len(res.multi_hand_landmarks)
                    scores = [0.0] * len(res.multi_hand_landmarks)

                for i, lm_obj in enumerate(res.multi_hand_landmarks):
                    lm = [(p.x, p.y, p.z) for p in lm_obj.landmark]
                    handed = labels[i] if i < len(labels) else None
                    score = scores[i] if i < len(scores) else 0.0

                    # Swap handedness if we mirrored the frame
                    if MIRROR_MODE and handed in ("Left", "Right"):
                        handed = "Right" if handed == "Left" else "Left"

                    hands_list.append((handed, lm))
                    hands_meta.append({"handed": handed, "score": float(score), "lm": lm})

            # rush left/right packs (hands-based default)
            rush_left, rush_right = (None, None)
            if self.rush_lr:
                rush_left, rush_right = self.rush_lr.pick(t, hands_list)

            # RUSH_COLOR: override with HSV stick tracking
            if str(self.mode).upper() == "RUSH_COLOR" and self.rush_color:
                try:
                    rush_left, rush_right = self.rush_color.process(frame, t)
                except Exception as e:
                    print("[RUSH_COLOR] tracker error:", e, flush=True)

            # ✅ Main hand policy: physical RIGHT hand is always the main/cursor hand.
            # We prefer MediaPipe handedness (after MIRROR swap above). If handedness is missing
            # (rare), we fall back to x-position with mirror awareness.
            cursor_lm = None  # main (RIGHT)
            other_lm = None   # aux  (LEFT)

            if hands_meta:
                rights = [h for h in hands_meta if h.get("handed") == "Right"]
                lefts = [h for h in hands_meta if h.get("handed") == "Left"]

                def _best(xs):
                    return max(xs, key=lambda h: float(h.get("score", 0.0))) if xs else None

                main_h = _best(rights)
                aux_h = _best(lefts)

                if main_h is not None:
                    cursor_lm = main_h["lm"]
                    if aux_h is not None:
                        other_lm = aux_h["lm"]
                    else:
                        # If there is another hand but it wasn't labeled LEFT, keep it as aux
                        others = [h for h in hands_meta if h is not main_h]
                        if others:
                            other_lm = _best(others)["lm"]
                else:
                    # Strict main-hand policy: if RIGHT hand is not present, keep cursor_lm=None.
                    # Still expose LEFT as aux so UI can show it.
                    if aux_h is not None:
                        other_lm = aux_h["lm"]

                    # Fallback when handedness is missing/None for all hands:
                    if (main_h is None) and (aux_h is None) and hands_list:
                        hands_with_pos = []
                        for label, lm in hands_list:
                            try:
                                cx, cy = palm_center(lm)
                            except Exception:
                                cx, cy = (0.5, 0.5)
                            hands_with_pos.append((cx, lm))
                        hands_with_pos.sort(key=lambda x: x[0])  # left -> right in mirrored frame

                        # In mirrored frame, physical RIGHT hand tends to appear on the LEFT side.
                        # Use the remaining hand as aux only (strict main policy).
                        if len(hands_with_pos) >= 1:
                            other_lm = hands_with_pos[-1][1]
            self.learner.tick_capture(cursor_lm=cursor_lm, other_lm=other_lm)

            got_cursor = (cursor_lm is not None)

            if got_cursor:
                cursor_cx, cursor_cy = palm_center(cursor_lm)

                ratio = float(getattr(self.learner, "pinch_ratio_thresh", {}).get("cursor", 0.35))
                base = _pinch_thresh_from_ratio(cursor_lm, ratio, fallback=0.06)
                pth = base * (self._pinch_hys_off if self._pinch_down else self._pinch_hys_on)

                cursor_gesture_raw = classify_gesture(cursor_lm, pinch_thresh=pth)

                now_s = time.time()
                raw_is_pinch = (cursor_gesture_raw == "PINCH_INDEX")
                pinch_down = self._update_pinch_state(raw_is_pinch, now_s)

                if pinch_down:
                    cursor_gesture_rule = "PINCH_INDEX"
                else:
                    cursor_gesture_rule = "OPEN_PALM" if cursor_gesture_raw == "PINCH_INDEX" else cursor_gesture_raw

                cursor_gesture = cursor_gesture_rule

                self.learner.tick_capture(cursor_lm=cursor_lm, other_lm=other_lm)

                pred, score = self.learner.predict("cursor", cursor_lm)
                sm_pred, sm_score = self._smooth_pred("cursor", pred, score, cursor_gesture_rule)

                mode_u = str(self.mode).upper()

                # ✅ FIX: PINCH는 learner가 절대 덮어쓰지 못하게 rule 우선
                if cursor_gesture_rule == "PINCH_INDEX":
                    cursor_gesture = "PINCH_INDEX"
                else:
                    if mode_u in ("DRAW", "VKEY", "KEYBOARD"):
                        cursor_gesture = cursor_gesture_rule
                    else:
                        if sm_pred is not None and str(sm_pred) != "PINCH_INDEX":
                            cursor_gesture = sm_pred
                        else:
                            cursor_gesture = cursor_gesture_rule

                self.learner.last_pred = {
                    "hand": "cursor",
                    "label": sm_pred,
                    "score": float(sm_score),
                    "rule": cursor_gesture_rule,
                    "rawLabel": pred,
                    "rawScore": float(score),
                }

                self.last_seen_ts = t
                self.last_cursor_lm = cursor_lm
                self.last_cursor_cxcy = (cursor_cx, cursor_cy)
                self.last_cursor_gesture = cursor_gesture

            else:
                if self.last_cursor_lm is not None and (t - self.last_seen_ts) <= LOSS_GRACE_SEC:
                    cursor_cx, cursor_cy = self.last_cursor_cxcy
                    cursor_gesture = self.last_cursor_gesture
                    cursor_lm = self.last_cursor_lm
                    got_cursor = True
                else:
                    cursor_gesture = "NONE"
                    cursor_cx, cursor_cy = (0.5, 0.5)
                    if self.last_cursor_lm is None or (t - self.last_seen_ts) >= HARD_LOSS_SEC:
                        self.reacquire_until = t + REACQUIRE_BLOCK_SEC
                        self._pinch_down = False
                        self._pinch_t0 = 0.0

            got_other = (other_lm is not None)
            other_gesture = "NONE"
            other_cx, other_cy = (0.5, 0.5)
            if got_other:
                other_cx, other_cy = palm_center(other_lm)
                ratio_o = float(getattr(self.learner, "pinch_ratio_thresh", {}).get("other", 0.35))
                pth_o = _pinch_thresh_from_ratio(other_lm, ratio_o, fallback=0.06)
                other_gesture = classify_gesture(other_lm, pinch_thresh=pth_o)

            mode_u = str(self.mode).upper()
            effective_locked = bool(self.ui_locked) or bool(self.locked)

            # Palette modal (최우선)
            block_by_palette = False
            if not self.ui_locked:
                block_by_palette = self._update_palette_modal(
                    t=t,
                    got_cursor=got_cursor,
                    got_other=got_other,
                    cursor_gesture=cursor_gesture,
                    other_gesture=other_gesture,
                    cursor_cx=cursor_cx,
                    cursor_cy=cursor_cy,
                )
            else:
                self._force_hide_menu()

            # -----------------------------------------------------------------
            # ✅ APP START/STOP (gesture -> 즉시 로컬 적용 + WS EVENT는 알림용)
            # - OPEN_PALM은 이동이랑 충돌 -> 사용 금지
            # - 정지 상태 Start: 양손 V_SIGN 홀드
            # - 실행 상태 Stop: 양손 FIST 홀드
            # -----------------------------------------------------------------
            if (not block_by_palette) and got_cursor and got_other:
                can_fire = (t >= (self.last_app_cmd_ts + APP_CMD_COOLDOWN_SEC))

                # START: enabled=False일 때만
                if (not self.enabled) and (cursor_gesture == "V_SIGN") and (other_gesture == "V_SIGN"):
                    if self.app_start_hold_start is None:
                        self.app_start_hold_start = t
                    if can_fire and (t - self.app_start_hold_start) >= APP_START_HOLD_SEC:
                        # ✅ 로컬에서 즉시 start 처리 (WS 의존 제거)
                        self.enabled = True
                        self.locked = False
                        # ui_locked는 유지(원하면 여기서 False로 풀어도 됨)

                        self.last_app_cmd_ts = t
                        self.app_start_hold_start = None
                        self.cursor_bubble = "START!"

                        # 알림용 이벤트(옵션)
                        try:
                            self.send_event("APP_START", {"source": "gesture"})
                        except Exception:
                            pass
                else:
                    self.app_start_hold_start = None

                # STOP: enabled=True일 때만
                if self.enabled and (cursor_gesture == "FIST") and (other_gesture == "FIST"):
                    if self.app_stop_hold_start is None:
                        self.app_stop_hold_start = t
                    if can_fire and (t - self.app_stop_hold_start) >= APP_STOP_HOLD_SEC:
                        # ✅ 로컬에서 즉시 stop 처리 (DISABLE과 동일한 처리)
                        self.enabled = False
                        self._reset_side_effects()
                        self._osk_close()
                        self._force_hide_menu()

                        self.last_app_cmd_ts = t
                        self.app_stop_hold_start = None
                        self.cursor_bubble = "STOP!"

                        # 알림용 이벤트(옵션)
                        try:
                            self.send_event("APP_STOP", {"source": "gesture"})
                        except Exception:
                            pass
                else:
                    self.app_stop_hold_start = None
            else:
                self.app_start_hold_start = None
                self.app_stop_hold_start = None


            # UI 잠금 토글 (FIST 홀드)
            block_osk_toggle_by_ui_lock = False

            if self.enabled and got_cursor and (cursor_gesture == "FIST") and (mode_u != "VKEY"):
                block_osk_toggle_by_ui_lock = True

                if self.ui_lock_hold_start is None:
                    self.ui_lock_hold_start = t

                if (t - self.ui_lock_hold_start) >= UI_LOCK_HOLD_SEC and t >= (
                    self.last_ui_lock_toggle_ts + UI_LOCK_COOLDOWN_SEC
                ):
                    self.ui_locked = (not self.ui_locked)
                    self.last_ui_lock_toggle_ts = t
                    self.ui_lock_hold_start = None

                    if self.ui_locked:
                        self._apply_ui_locked_side_effects()
                        self.cursor_bubble = "UI 잠금!"
                    else:
                        self.cursor_bubble = "UI 해제!"

                    try:
                        self.send_event("UI_LOCK", {"locked": bool(self.ui_locked)})
                    except Exception:
                        pass
            else:
                self.ui_lock_hold_start = None

            # UI menu (HUD)
            if (not block_by_palette) and (not self.ui_locked) and self.ui_menu:
                _ = self.ui_menu.update(
                    t=t,
                    enabled=self.enabled,
                    mode=self.mode,
                    cursor_gesture=cursor_gesture,
                    other_gesture=other_gesture,
                    got_other=got_other,
                    send_event=lambda name, payload: self.send_event(name, payload),
                )

            # VKEY에서 OSK 토글 사인: FIST 홀드
            if (
                (not block_by_palette)
                and (not self.ui_locked)
                and (not block_osk_toggle_by_ui_lock)
                and mode_u == "VKEY"
                and self.enabled
            ):
                if cursor_gesture == "FIST":
                    if self.osk_toggle_hold_start is None:
                        self.osk_toggle_hold_start = t
                    if (t - self.osk_toggle_hold_start) >= OSK_TOGGLE_HOLD_SEC and t >= (
                        self.last_osk_toggle_ts + OSK_TOGGLE_COOLDOWN_SEC
                    ):
                        self._osk_toggle()
                        self.last_osk_toggle_ts = t
                        self.osk_toggle_hold_start = None
                        self.cursor_bubble = "OSK 토글!"
                else:
                    self.osk_toggle_hold_start = None
            else:
                self.osk_toggle_hold_start = None

            # NEXT_MODE when locked: both OPEN_PALM hold
            if (
                (not block_by_palette)
                and (not self.ui_locked)
                and self.enabled
                and self.locked
                and got_other
                and (cursor_gesture == "OPEN_PALM")
                and (other_gesture == "OPEN_PALM")
            ):
                if self.mode_hold_start is None:
                    self.mode_hold_start = t
                if (t - self.mode_hold_start) >= MODE_HOLD_SEC and t >= (
                    self.last_mode_event_ts + MODE_COOLDOWN_SEC
                ):
                    self.send_event("NEXT_MODE", None)
                    self.last_mode_event_ts = t
                    self.mode_hold_start = None
            else:
                self.mode_hold_start = None

            mouse_move_g = get_binding(self.settings, "MOUSE", "MOVE", default="OPEN_PALM")
            mouse_click_g = get_binding(self.settings, "MOUSE", "CLICK_DRAG", default="PINCH_INDEX")
            mouse_right_g = get_binding(self.settings, "MOUSE", "RIGHT_CLICK", default="V_SIGN")
            mouse_lock_g = get_binding(self.settings, "MOUSE", "LOCK_TOGGLE", default="FIST")
            mouse_scroll_hold_g = get_binding(self.settings, "MOUSE", "SCROLL_HOLD", default="FIST")

            kb_bindings = ((self.settings.get("bindings") or {}).get("KEYBOARD") or {})
            ppt_bindings = ((self.settings.get("bindings") or {}).get("PRESENTATION") or {})

            # LOCK only in MOUSE
            if (not block_by_palette) and (not self.ui_locked) and mode_u == "MOUSE" and self.mouse_lock:
                self.locked = self.mouse_lock.update(
                    t=t,
                    cursor_gesture=cursor_gesture,
                    cx=cursor_cx,
                    cy=cursor_cy,
                    got_cursor=got_cursor,
                    got_other=got_other,
                    enabled=self.enabled,
                    locked=self.locked,
                    toggle_gesture=mouse_lock_g,
                )
            else:
                if self.mouse_lock:
                    self.mouse_lock.reset()

            no_inject = bool(getattr(self.cfg, "no_inject", False))
            can_mouse_inject = (
                self.enabled
                and (mode_u == "MOUSE")
                and (t >= self.reacquire_until)
                and (not effective_locked)
                and (not no_inject)
            )
            can_draw_inject = (
                self.enabled
                and (mode_u == "DRAW")
                and (t >= self.reacquire_until)
                and (not effective_locked)
                and (not no_inject)
            )
            can_kb_inject = (
                self.enabled
                and (mode_u == "KEYBOARD")
                and (t >= self.reacquire_until)
                and (not effective_locked)
                and (not no_inject)
            )

            kb_mouse_mod_g = get_binding(self.settings, "KEYBOARD", "MOUSE_MOD", default="FIST")
            kb_mouse_gate = bool(got_other and (other_gesture == kb_mouse_mod_g))

            # HUD/status에 게이트 상태도 노출(설정 바꿔도 말풍선/패널이 따라오게)
            self._kb_mouse_gate = bool(kb_mouse_gate)
            self._kb_mouse_mod_g = str(kb_mouse_mod_g)

            # ✅ KEYBOARD에서 '두손 조합'일 때만 마우스 커서/클릭 허용
            can_mouse_inject_kb = (
                self.enabled
                and (mode_u == "KEYBOARD")
                and (t >= self.reacquire_until)
                and (not effective_locked)
                and (not no_inject)
                and kb_mouse_gate
            )

            # HUD/상태 표시용(말풍선에서 KEYBOARD 내 마우스 게이트 구분)
            try:
                self._kb_mouse_gate = bool(can_mouse_inject_kb)
                self._kb_mouse_mod_g = str(kb_mouse_mod_g)
            except Exception:
                pass


            can_ppt_inject = (
                self.enabled
                and (mode_u == "PRESENTATION")
                and (t >= self.reacquire_until)
                and (not effective_locked)
                and (not no_inject)
            )
            can_vkey_detect = self.enabled and (mode_u == "VKEY")
            can_vkey_click = can_vkey_detect

            if mode_u.startswith("RUSH"):
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                can_vkey_detect = False
                can_vkey_click = False
                can_mouse_inject_kb = False

            # VKEY: OSK는 띄우기만, 입력은 OS 커서 이동+클릭으로 처리
            if mode_u == "VKEY":
                self.locked = False
                can_mouse_inject = (
                    self.enabled
                    and (t >= self.reacquire_until)
                    and (not no_inject)
                    and (not self.ui_locked)
                )
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                can_vkey_detect = True
                can_vkey_click = True

            # Palette active면 기존 동작 모두 차단
            if block_by_palette:
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                can_vkey_detect = False
                can_vkey_click = False
                can_mouse_inject_kb = False

            # UI 잠금이면 최종적으로 전부 차단
            if self.ui_locked:
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                can_vkey_detect = False
                can_vkey_click = False
                can_mouse_inject_kb = False

            # pointer move
            can_pointer_inject = (can_mouse_inject or can_draw_inject or can_ppt_inject or can_kb_inject)
            if (not block_by_palette) and can_pointer_inject and got_cursor:
                do_move = False
                if mode_u in ("MOUSE", "VKEY"):
                    dragging = bool(getattr(self.mouse_click, "dragging", False)) if self.mouse_click else False
                    do_move = (cursor_gesture == mouse_move_g) or (dragging and cursor_gesture == mouse_click_g)
                elif mode_u == "DRAW":
                    down = bool(getattr(self.draw, "down", False)) if self.draw else False
                    do_move = (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX")) or down
                elif mode_u == "PRESENTATION":
                    do_move = (cursor_gesture == "OPEN_PALM")
                elif mode_u == "KEYBOARD":
                    # KEYBOARD: other-hand gate(MOUSE_MOD)일 때만 커서 이동
                    if can_mouse_inject_kb:
                        dragging = bool(getattr(self.mouse_click, "dragging", False)) if self.mouse_click else False
                        do_move = (cursor_gesture == mouse_move_g) or (dragging and cursor_gesture == mouse_click_g)
                    else:
                        do_move = False


                if do_move:
                    ux, uy = self.control.map_control_to_screen(cursor_cx, cursor_cy)
                    ex, ey = self.control.apply_ema(ux, uy)
                    self.control.move_cursor(ex, ey, t)

            # -------------------------------------------------------------
            # ✅ 핵심: VKEY/KEYBOARD에서 PINCH를 SendInput 좌클릭으로 강제 주입
            # -------------------------------------------------------------
            if _IS_WIN and (mode_u == "VKEY") and self.enabled and (not self.ui_locked) and (not block_by_palette):
                is_pinch = (str(cursor_gesture).upper() == "PINCH_INDEX")
                if is_pinch and (not self._vkey_prev_pinch):
                    if (t >= (self._vkey_last_click_ts + self._vkey_click_cd)) and (t >= self.reacquire_until) and (not no_inject):
                        try:
                            _win_left_click()
                            self._vkey_last_click_ts = t
                        except Exception:
                            pass
                self._vkey_prev_pinch = is_pinch
            else:
                self._vkey_prev_pinch = False

            # mouse actions
            if mode_u in ("MOUSE", "KEYBOARD"):
                allow_click = (
                    (can_mouse_inject and (not block_by_palette))
                    or (can_mouse_inject_kb and (not block_by_palette))
                )

                if self.mouse_click:
                    self.mouse_click.update(
                        t,
                        cursor_gesture,
                        allow_click,
                        click_gesture=mouse_click_g,
                    )

                # 우클릭: MOUSE, KEYBOARD(두손 조합 게이트일 때)
                if self.mouse_right:
                    can_rc = (can_mouse_inject if mode_u == "MOUSE" else can_mouse_inject_kb) and (not block_by_palette)
                    self.mouse_right.update(
                        t,
                        cursor_gesture,
                        can_rc,
                        gesture=mouse_right_g,
                    )

            else:
                # ✅ VKEY 포함: MouseClickDrag/RightClick 완전 OFF (VKEY는 _win_left_click()만 사용)
                if self.mouse_click:
                    self.mouse_click.update(t, cursor_gesture, False, click_gesture=mouse_click_g)
                if self.mouse_right:
                    self.mouse_right.update(t, cursor_gesture, False, gesture=mouse_right_g)


            # draw
            if mode_u == "DRAW" and self.draw:
                if not block_by_palette:
                    self.draw.update_draw(t, cursor_gesture, can_draw_inject)
                    self.draw.update_selection_shortcuts(
                        t, cursor_gesture, other_gesture, got_other, can_draw_inject
                    )
                else:
                    self.draw.reset()
            else:
                if self.draw:
                    self.draw.reset()

            # presentation
            if mode_u == "PRESENTATION" and self.ppt:
                if not block_by_palette:
                    self.ppt.update(
                        t,
                        can_ppt_inject,
                        got_cursor,
                        cursor_gesture,
                        got_other,
                        other_gesture,
                        bindings=ppt_bindings,
                    )
                else:
                    self.ppt.reset()
            else:
                if self.ppt:
                    self.ppt.reset()

            # scroll (MOUSE only)
            scroll_active = False
            if (
                (mode_u == "MOUSE")
                and (not block_by_palette)
                and can_mouse_inject
                and got_other
                and self.mouse_scroll
            ):
                sa = (other_gesture == mouse_scroll_hold_g)
                self.mouse_scroll.update(t, sa, other_cy, True)
                scroll_active = sa
            else:
                if self.mouse_scroll:
                    self.mouse_scroll.update(t, False, 0.5, False)

            # keyboard (KEYBOARD 모드에서도 키입력은 유지하되, 마우스 게이트 중 충돌 제스처는 무시)
            # keyboard
            if (not block_by_palette) and self.kb:
                # ✅ 키보드 입력은 KEYBOARD 모드에서 항상 켠다
                kb_can = can_kb_inject

                # ✅ KEYBOARD에서 다른 손 FIST(MOUSE_MOD)로 마우스 게이트가 켜진 상태면
                # OPEN_PALM/PINCH_INDEX는 "마우스 이동/클릭"로 쓰이므로
                # 키보드 방향키(UP/DOWN)로도 같이 발사되는 걸 막는다.
                cursor_g_for_kb = cursor_gesture
                if can_mouse_inject_kb:
                    if cursor_gesture in (mouse_move_g, mouse_click_g):  # 기본: OPEN_PALM, PINCH_INDEX
                        cursor_g_for_kb = "NONE"

                # 디버그: 키보드 파이프라인 상태(왜 안 나가는지) 출력
                if os.getenv("KEYBOARD_DEBUG", "0") in ("1", "true", "True", "YES", "yes"):
                    try:
                        if (t - float(getattr(self, "_kb_dbg_last_ts", 0.0))) >= 0.25:
                            self._kb_dbg_last_ts = t
                            print(
                                "[KB_PIPE]",
                                f"enabled={self.enabled}",
                                f"mode={mode_u}",
                                f"kb_can={kb_can}",
                                f"kb_mouse_gate={can_mouse_inject_kb}",
                                f"ui_locked={self.ui_locked}",
                                f"locked={self.locked}",
                                f"reacquire_in={max(0.0, self.reacquire_until - t):.3f}",
                                f"got_cursor={got_cursor}",
                                f"cursor={cursor_gesture}->{cursor_g_for_kb}",
                                f"got_other={got_other}",
                                f"other={other_gesture}",
                                flush=True,
                            )
                    except Exception:
                        pass

                self.kb.update(
                    t,
                    kb_can,
                    got_cursor,
                    cursor_g_for_kb,
                    got_other,
                    other_gesture,
                    bindings=kb_bindings,
                )
            else:
                if self.kb:
                    self.kb.reset()


            self._send_status(
                fps=fps,
                cursor_gesture=cursor_gesture,
                other_gesture=other_gesture,
                scroll_active=scroll_active,
                can_mouse=(can_mouse_inject or can_draw_inject or can_ppt_inject or can_mouse_inject_kb or (mode_u == "VKEY")),
                can_key=(can_kb_inject or can_ppt_inject),
                rush_left=rush_left,
                rush_right=rush_right,
                cursor_lm=cursor_lm,
                other_lm=other_lm,
                cursor_cx=cursor_cx,
                cursor_cy=cursor_cy,
                got_cursor=got_cursor,
            )

            # preview
            if bool(getattr(self.cfg, "headless", False)) and (not self.preview):
                time.sleep(0.001)
                continue

            if self.preview:
                if not self.window_open:
                    cv2.namedWindow("GestureOS Agent", cv2.WINDOW_NORMAL)
                    self.window_open = True

                lp = _pack_xy(rush_left)
                rp = _pack_xy(rush_right)

                line1 = (
                    f"mode={mode_u} enabled={self.enabled} locked={self.locked} ui_locked={self.ui_locked} "
                    f"cur={cursor_gesture} oth={other_gesture} palette={self.palette_active}"
                )
                cv2.putText(frame, line1, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

                if lp is not None:
                    cv2.putText(
                        frame,
                        f"RUSH L: ({lp[0]:.2f},{lp[1]:.2f})",
                        (10, 100),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 0),
                        2,
                    )
                if rp is not None:
                    cv2.putText(
                        frame,
                        f"RUSH R: ({rp[0]:.2f},{rp[1]:.2f})",
                        (10, 125),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 0, 255),
                        2,
                    )

                cv2.imshow("GestureOS Agent", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break

            else:
                if self._request_close_preview or self.window_open:
                    try:
                        cv2.destroyWindow("GestureOS Agent")
                    except Exception:
                        try:
                            cv2.destroyAllWindows()
                        except Exception:
                            pass
                    self.window_open = False
                    self._request_close_preview = False

        # cleanup
        self._close_camera()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # status
    # -------------------------------------------------------------------------
    def _send_status(
        self,
        fps: float,
        cursor_gesture: str,
        other_gesture: str,
        scroll_active: bool,
        can_mouse: bool,
        can_key: bool,
        rush_left,
        rush_right,
        cursor_lm,
        other_lm,
        cursor_cx: float,
        cursor_cy: float,
        got_cursor: bool,
    ):
        if getattr(self.cfg, "no_ws", False):
            return

        mode_u = str(self.mode).upper()

        lp = _pack_xy(rush_left)
        rp = _pack_xy(rush_right)

        effective_locked = bool(self.ui_locked) or bool(self.locked)

        payload = {
            "type": "STATUS",
            "enabled": bool(self.enabled),
            "mode": mode_u,
            "locked": bool(effective_locked),
            "uiLocked": bool(self.ui_locked),
            "gestureLocked": bool(self.locked),
            "preview": bool(self.preview),
            "gesture": str(cursor_gesture),
            "fps": float(fps),
            "canMove": bool(can_mouse and (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX"))),
            "canClick": bool(
                (can_mouse and (cursor_gesture in ("PINCH_INDEX", "V_SIGN")))
                or (mode_u == "VKEY" and self.enabled and cursor_gesture == "PINCH_INDEX")
                or (mode_u == "KEYBOARD" and self.enabled and cursor_gesture == "PINCH_INDEX")
            ),
            "scrollActive": bool(scroll_active),
            "canKey": bool(can_key),
            "otherGesture": str(other_gesture),
            "cursorLandmarks": _lm_to_payload(cursor_lm),
            "otherLandmarks": _lm_to_payload(other_lm),
            "connected": bool(self.ws.connected),
            "cameraOk": bool(self._cam_ok),
            "cameraErr": str(self._cam_err) if self._cam_err else "",
            "learnProfile": str(getattr(self.learner, "profile", "default")),
            "learnProfiles": list(getattr(self.learner, "list_profiles", lambda: ["default"])()),
            "learnEnabled": bool(self.learner.enabled),
            "learnCounts": self.learner.counts(),
            "learnLastPred": self.learner.last_pred,
            "learnLastTrainTs": float(self.learner.last_train_ts or 0.0),
            "learnCapture": self.learner.capture,
            "learnHasBackup": bool(getattr(self.learner, "has_backup", lambda: False)()),
            "gain": float(getattr(self.control, "gain", 1.0)),
        }

        # --- mode-specific extra fields ---
        if mode_u == "KEYBOARD":
            try:
                kb_bind = ((self.settings.get("bindings") or {}).get("KEYBOARD") or {})
                base = kb_bind.get("BASE") if isinstance(kb_bind.get("BASE"), dict) else {}
                fn = kb_bind.get("FN") if isinstance(kb_bind.get("FN"), dict) else {}
                fn_hold = kb_bind.get("FN_HOLD")
                payload["kbBase"] = dict(base)
                payload["kbFn"] = dict(fn)
                if fn_hold:
                    payload["kbFnHold"] = str(fn_hold)

                # KEYBOARD에서 마우스 게이트(두손 조합) 상태
                payload["kbMouseGate"] = bool(getattr(self, "_kb_mouse_gate", False))
                payload["kbMouseMod"] = str(getattr(self, "_kb_mouse_mod_g", ""))
            except Exception:
                pass

        if mode_u == "MOUSE":
            try:
                m_bind = ((self.settings.get("bindings") or {}).get("MOUSE") or {})
                if isinstance(m_bind, dict):
                    payload["mouseBindings"] = dict(m_bind)
            except Exception:
                pass

        if mode_u == "PRESENTATION":
            try:
                ppt_bind = ((self.settings.get("bindings") or {}).get("PRESENTATION") or {})
                if isinstance(ppt_bind, dict):
                    nav = ppt_bind.get("NAV") if isinstance(ppt_bind.get("NAV"), dict) else {}
                    inter = ppt_bind.get("INTERACT") if isinstance(ppt_bind.get("INTERACT"), dict) else {}
                    hold = ppt_bind.get("INTERACT_HOLD")
                    payload["pptNav"] = dict(nav)
                    payload["pptInteract"] = dict(inter)
                    if hold:
                        payload["pptInteractHold"] = str(hold)
            except Exception:
                pass

        # --- common HUD/UI fields (모드와 무관하게 항상 나가야 함) ---
        if getattr(self, "cursor_bubble", None):
            payload["cursorBubble"] = str(self.cursor_bubble)

        if mode_u.startswith("RUSH"):
            payload["rushInput"] = "COLOR" if mode_u == "RUSH_COLOR" else "HAND"

        payload["pointerX"] = None
        payload["pointerY"] = None
        payload["isTracking"] = False

        if lp is not None:
            payload["leftPointerX"], payload["leftPointerY"] = lp
            payload["leftTracking"] = True
        else:
            payload["leftTracking"] = False

        if rp is not None:
            payload["rightPointerX"], payload["rightPointerY"] = rp
            payload["rightTracking"] = True
        else:
            payload["rightTracking"] = False

        if mode_u.startswith("RUSH"):
            if rp is not None:
                payload["pointerX"], payload["pointerY"] = rp
                payload["isTracking"] = True
            elif lp is not None:
                payload["pointerX"], payload["pointerY"] = lp
                payload["isTracking"] = True

        elif mode_u == "VKEY" and cursor_lm is not None:
            payload["pointerX"] = float(cursor_lm[8][0])
            payload["pointerY"] = float(cursor_lm[8][1])
            payload["isTracking"] = True

        elif got_cursor:
            x01, y01 = _get_os_cursor_norm01()
            if x01 is not None and y01 is not None:
                payload["pointerX"] = float(x01)
                payload["pointerY"] = float(y01)
                payload["isTracking"] = True
            else:
                payload["pointerX"] = float(cursor_cx)
                payload["pointerY"] = float(cursor_cy)
                payload["isTracking"] = True

        payload["tracking"] = bool(payload.get("isTracking", False))

        # --- send WS + HUD ---
        self.ws.send_dict(payload)

        hud = getattr(self.cfg, "hud", None)
        if hud:
            hud_payload = dict(payload)
            hud_payload["connected"] = bool(self.ws.connected)
            hud_payload["tracking"] = bool(payload.get("isTracking", False))
            hud.push(hud_payload)

            # 첫 push 이후 1회 강제 refresh
            if (not self._hud_bootstrap_done) and (time.time() - self._hud_bootstrap_t0 >= 0.3):
                self._hud_bootstrap_done = True
                try:
                    hud.force_refresh()
                except Exception:
                    pass

