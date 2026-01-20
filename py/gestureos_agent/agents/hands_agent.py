# file: py/gestureos_agent/agents/hands_agent.py
import os
import time
import ctypes
import subprocess
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

# ✅ HUD의 "키보드"를 VKEY(윈도우 OSK)로 매핑
PALETTE_MAP = {
    "MOUSE": "MOUSE",
    "KEYBOARD": "VKEY",
    "DRAW": "DRAW",
    "PPT": "PRESENTATION",
    "OTHER": "MOUSE",
}

# =============================================================================
# OSK toggle gesture (VKEY only)
# =============================================================================
OSK_TOGGLE_HOLD_SEC = 0.8
OSK_TOGGLE_COOLDOWN_SEC = 1.2


def _lm_to_payload(lm):
    if lm is None:
        return []
    return [{"x": float(p[0]), "y": float(p[1]), "z": float(p[2])} for p in lm]


def _pack_xy(p: Optional[dict]):
    """accept both (cx,cy) or (nx,ny) packs"""
    if p is None:
        return None
    cx = p.get("cx", p.get("nx"))
    cy = p.get("cy", p.get("ny"))
    if cx is None or cy is None:
        return None
    return float(cx), float(cy)


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
        self.cursor_hand_label = "Left" if getattr(cfg, "force_cursor_left", False) else "Right"

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

        # ---- OSK state ----
        self.osk_open = False
        self.osk_toggle_hold_start = None
        self.last_osk_toggle_ts = 0.0

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

        # ws
        self.ws = WSClient(
            getattr(cfg, "ws_url", "ws://127.0.0.1:8080/ws/agent"),
            self._on_command,
            enabled=(not getattr(cfg, "no_ws", False)),
        )

        # boot: start_vkey면 바로 OSK 띄우기
        if str(self.mode).upper() == "VKEY":
            self._enter_vkey_mode()

    # -------------------------------------------------------------------------
    # OSK helpers
    # -------------------------------------------------------------------------
    def _osk_open(self):
        if os.name != "nt":
            return
        if self.osk_open:
            return

        launched_any = False

        # 1) TabTip (떠도 UI가 안 뜰 수 있음)
        tabtip = r"C:\Program Files\Common Files\Microsoft Shared\ink\TabTip.exe"
        try:
            if os.path.exists(tabtip):
                subprocess.Popen([tabtip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[VKEY] launched TabTip", flush=True)
                launched_any = True
                time.sleep(0.05)
        except Exception as e:
            print("[VKEY] TabTip failed:", repr(e), flush=True)

        # 2) Win11 URI (옵션)
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", "ms-inputapp:"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[VKEY] launched ms-inputapp:", flush=True)
            launched_any = True
            time.sleep(0.05)
        except Exception as e:
            print("[VKEY] ms-inputapp failed:", repr(e), flush=True)

        # 3) ✅ 가장 확실: classic OSK
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", "osk.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[VKEY] launched osk.exe", flush=True)
            launched_any = True
        except Exception as e:
            print("[VKEY] osk.exe failed:", repr(e), flush=True)

        if launched_any:
            self.osk_open = True

    def _osk_close(self):
        if os.name != "nt":
            return
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
        self.osk_open = False

    def _osk_toggle(self):
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
        ):
            print("[PY] cmd:", data, flush=True)

        if typ == "ENABLE":
            self.enabled = True
            # ✅ enabled는 켜되, UI 잠금은 유지 (프론트 토글 기준)
            self.locked = False

        elif typ == "DISABLE":
            self.enabled = False
            self._reset_side_effects()
            # ✅ Stop 누르면 OSK도 끄기
            self._osk_close()

        elif typ == "SET_LOCK" or typ == "SET_LOCKED":
            # payload 예: {"type":"SET_LOCK","enabled":true} or {"locked":true}
            v = data.get("enabled", data.get("locked", True))
            self.ui_locked = bool(v)

            # ✅ 잠그는 순간 드래그/키다운/스크롤 같은 사이드이펙트 즉시 해제 + 팔레트 닫기
            if self.ui_locked:
                self._reset_side_effects()
                hud = getattr(self.cfg, "hud", None)
                if hud and self.palette_active:
                    try:
                        hud.hide_menu()
                    except Exception:
                        pass
                self.palette_active = False
                self.palette_open_start = None
                self.palette_confirm_start = None
                self.palette_cancel_start = None

        elif typ == "LOCK":
            self.ui_locked = True
            self._reset_side_effects()
            hud = getattr(self.cfg, "hud", None)
            if hud and self.palette_active:
                try:
                    hud.hide_menu()
                except Exception:
                    pass
            self.palette_active = False
            self.palette_open_start = None
            self.palette_confirm_start = None
            self.palette_cancel_start = None

        elif typ == "UNLOCK":
            self.ui_locked = False

        elif typ == "SET_MODE":
            new_mode = str(data.get("mode", "MOUSE")).upper()
            self.apply_set_mode(new_mode)

        elif typ == "SET_PREVIEW":
            enabled = bool(data.get("enabled", True))
            self.preview = enabled
            print(f"[PY] preview set -> {enabled} (window_open={self.window_open})", flush=True)

            # 프리뷰 OFF면 창을 즉시 닫기 (창이 "안 없어지는" 문제 해결)
            if not enabled:
                self._request_close_preview = True

        elif typ == "UPDATE_SETTINGS":
            incoming = data.get("settings") or {}
            self.apply_settings(incoming)

    # -------------------------------------------------------------------------
    # mode + state
    # -------------------------------------------------------------------------
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

    def apply_settings(self, incoming: dict):
        try:
            self.settings = merge_settings(self.settings, incoming)
            print("[PY] apply_settings -> version", self.settings.get("version"), flush=True)
        except Exception as e:
            print("[PY] apply_settings failed:", e, flush=True)

    # ---------- VKEY helpers ----------
    def _enter_vkey_mode(self):
        """VKEY 진입 시: 윈도우 가상 키보드(터치 키보드/osk) 띄우기."""
        # keyboard.py가 on_enter 지원하면 호출(있어도 최종 OSK는 띄움)
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

        # ✅ 최종: OSK 강제
        self._osk_open()

    def apply_set_mode(self, new_mode: str):
        prev_mode = str(self.mode).upper()

        nm = str(new_mode).upper()
        if nm == "PPT":
            nm = "PRESENTATION"
        if nm == "PAINT":
            nm = "DRAW"

        # aliases(레거시 호환)
        if nm == "RUSH":
            nm = "RUSH_HAND"
        if nm in ("RUSH_STICK", "RUSH_COLOR_STICK"):
            nm = "RUSH_COLOR"

        allowed = {"MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "VKEY", "RUSH_HAND", "RUSH_COLOR"}
        if nm not in allowed:
            print("[PY] apply_set_mode ignored:", new_mode, flush=True)
            return

        # ✅ VKEY에서 다른 모드로 나가면 OSK 닫기
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
        print("[PY] apply_set_mode ->", self.mode, flush=True)

        # ✅ VKEY 진입 시 OSK 띄우기
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

    # -------------------------------------------------------------------------
    # palette modal
    # -------------------------------------------------------------------------
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
            self.palette_active = False
            self.palette_open_start = None
            self.palette_confirm_start = None
            self.palette_cancel_start = None
            return False

        # -----------------------
        # open trigger (inactive -> active)
        # -----------------------
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
                # ✅ 팔레트 열리는 "순간"에만 OSK 상태 저장 + 닫기
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

        # palette active: hover + confirm/cancel
        hover = hud.get_menu_hover()  # "MOUSE"/"KEYBOARD"/"DRAW"/"PPT"/"OTHER"/None
        self.cursor_bubble = f"MENU • {hover or '...'} (PINCH=확정, FIST=취소)"

        # allow cursor move (OPEN_PALM) only for selecting items
        no_inject = bool(getattr(self.cfg, "no_inject", False))
        if (not no_inject) and (t >= self.reacquire_until) and got_cursor and (cursor_gesture == "OPEN_PALM"):
            ux, uy = self.control.map_control_to_screen(cursor_cx, cursor_cy)
            ex, ey = self.control.apply_ema(ux, uy)
            self.control.move_cursor(ex, ey, t)

        # confirm
        if (cursor_gesture == "PINCH_INDEX") and hover:
            if self.palette_confirm_start is None:
                self.palette_confirm_start = t
            if (t - self.palette_confirm_start) >= PALETTE_CONFIRM_HOLD:
                picked = PALETTE_MAP.get(str(hover).upper(), "MOUSE")
                self.apply_set_mode(picked)

                hud.hide_menu()
                self.palette_active = False
                self.palette_confirm_start = None
                self.palette_cancel_start = None
                self._reset_side_effects()

                # ✅ 팔레트 닫힌 뒤 복구: 결과가 VKEY이고, 열기 전 OSK가 켜져있었으면 다시 켜기
                if str(self.mode).upper() == "VKEY" and self.palette_prev_osk_open:
                    self._osk_open()
                self.palette_prev_osk_open = False
        else:
            self.palette_confirm_start = None

        # cancel
        if cursor_gesture == "FIST":
            if self.palette_cancel_start is None:
                self.palette_cancel_start = t
            if (t - self.palette_cancel_start) >= PALETTE_CANCEL_HOLD:
                hud.hide_menu()
                self.palette_active = False
                self.palette_confirm_start = None
                self.palette_cancel_start = None
                self._reset_side_effects()

                # ✅ 취소도 복구: 현재 모드가 VKEY이고, 열기 전 OSK가 켜져있었으면 다시 켜기
                if str(self.mode).upper() == "VKEY" and self.palette_prev_osk_open:
                    self._osk_open()
                self.palette_prev_osk_open = False
        else:
            self.palette_cancel_start = None

        return bool(self.palette_active)

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

        cap = self._open_camera()
        self.ws.start()

        prev_t = now()
        fps = 0.0

        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            t = now()
            dt = max(t - prev_t, 1e-6)
            prev_t = t
            fps = 0.9 * fps + 0.1 * (1.0 / dt)

            res = self.hands.process(rgb)

            hands_list: List[Tuple[Optional[str], Any]] = []
            if res.multi_hand_landmarks:
                labels = []
                if res.multi_handedness:
                    for h in res.multi_handedness:
                        labels.append(h.classification[0].label)
                else:
                    labels = [None] * len(res.multi_hand_landmarks)

                for i, lm_obj in enumerate(res.multi_hand_landmarks):
                    lm = [(p.x, p.y, p.z) for p in lm_obj.landmark]
                    label = labels[i] if i < len(labels) else None
                    hands_list.append((label, lm))

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

            # cursor / other selection
            cursor_lm = None
            other_lm = None
            if hands_list:
                for label, lm in hands_list:
                    if label == self.cursor_hand_label:
                        cursor_lm = lm
                        break
                if cursor_lm is None:
                    cursor_lm = hands_list[0][1]

                if len(hands_list) >= 2:
                    for _label, lm in hands_list:
                        if lm is not cursor_lm:
                            other_lm = lm
                            break

            got_cursor = (cursor_lm is not None)
            if got_cursor:
                cursor_cx, cursor_cy = palm_center(cursor_lm)
                cursor_gesture = classify_gesture(cursor_lm)
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

            got_other = (other_lm is not None)
            other_gesture = "NONE"
            other_cx, other_cy = (0.5, 0.5)
            if got_other:
                other_cx, other_cy = palm_center(other_lm)
                other_gesture = classify_gesture(other_lm)

            mode_u = str(self.mode).upper()

            # ✅ UI 잠금(프론트 토글) + gesture lock 을 합친 "실제 잠김" 상태
            effective_locked = bool(self.ui_locked) or bool(self.locked)

            # ============================================================
            # Palette modal (최우선)  (단, UI 잠금 중이면 제스처로 열지 못하게)
            # ============================================================
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
                # UI 잠김이면 팔레트가 열려있던 것도 강제 비활성(안전)
                if self.palette_active:
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

            # UI menu (HUD) (UI 잠금 중이면 제스처 처리 막기)
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

            # ✅ VKEY에서 OSK 토글 사인: 주먹(FIST) 0.8초 홀드 (UI 잠금 중이면 막기)
            if (not block_by_palette) and (not self.ui_locked) and mode_u == "VKEY" and self.enabled:
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

            # NEXT_MODE when locked: both OPEN_PALM hold (팔레트 중엔 막기, UI 잠금 중엔 막기)
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

            # ---- bindings (read live) ----
            mouse_move_g = get_binding(self.settings, "MOUSE", "MOVE", default="OPEN_PALM")
            mouse_click_g = get_binding(self.settings, "MOUSE", "CLICK_DRAG", default="PINCH_INDEX")
            mouse_right_g = get_binding(self.settings, "MOUSE", "RIGHT_CLICK", default="V_SIGN")
            mouse_lock_g = get_binding(self.settings, "MOUSE", "LOCK_TOGGLE", default="FIST")
            mouse_scroll_hold_g = get_binding(self.settings, "MOUSE", "SCROLL_HOLD", default="FIST")

            kb_bindings = ((self.settings.get("bindings") or {}).get("KEYBOARD") or {})
            ppt_bindings = ((self.settings.get("bindings") or {}).get("PRESENTATION") or {})

            # LOCK only in MOUSE (팔레트 중엔 막기, UI 잠금 중엔 막기)
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

            # injection permissions
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
            can_ppt_inject = (
                self.enabled
                and (mode_u == "PRESENTATION")
                and (t >= self.reacquire_until)
                and (not effective_locked)
                and (not no_inject)
            )
            can_vkey_detect = self.enabled and (mode_u == "VKEY")
            can_vkey_click = can_vkey_detect

            # RUSH disables OS inject
            if mode_u.startswith("RUSH"):
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                can_vkey_detect = False
                can_vkey_click = False

            # VKEY: OSK는 띄우기만, 입력은 OS 커서 이동+클릭으로 처리
            if mode_u == "VKEY":
                # 기존 정책 유지: gesture lock은 무의미하게 풀어둠
                self.locked = False
                # ✅ 하지만 UI 잠금이면 제스처 주입은 막아야 함
                can_mouse_inject = self.enabled and (t >= self.reacquire_until) and (not no_inject) and (not self.ui_locked)
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

            # UI 잠금이면 최종적으로 전부 차단(팔레트보다 바깥 안전망)
            if self.ui_locked:
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                # detect는 유지해도 되지만, 클릭/이동은 막아야 하니까 아래에서 move/click이 다 막힘
                # (STATUS에서 tracking 표시는 계속 가능)
                # can_vkey_detect/can_vkey_click은 여기서 끄면 OSK 관련도 완전 정지됨
                can_vkey_detect = False
                can_vkey_click = False

            # pointer move
            can_pointer_inject = (can_mouse_inject or can_draw_inject or can_ppt_inject)
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

                if do_move:
                    ux, uy = self.control.map_control_to_screen(cursor_cx, cursor_cy)
                    ex, ey = self.control.apply_ema(ux, uy)
                    self.control.move_cursor(ex, ey, t)

            # mouse actions
            if mode_u in ("MOUSE", "VKEY"):
                if self.mouse_click:
                    self.mouse_click.update(
                        t,
                        cursor_gesture,
                        can_mouse_inject and (not block_by_palette),
                        click_gesture=mouse_click_g,
                    )
                if mode_u == "MOUSE" and self.mouse_right:
                    self.mouse_right.update(
                        t,
                        cursor_gesture,
                        can_mouse_inject and (not block_by_palette),
                        gesture=mouse_right_g,
                    )
            else:
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

            # scroll (MOUSE only) ✅ VKEY에서 스크롤 제스처가 OSK 클릭을 방해할 수 있어서 차단
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

            # keyboard
            if (not block_by_palette) and self.kb:
                self.kb.update(
                    t,
                    can_kb_inject,
                    got_cursor,
                    cursor_gesture,
                    got_other,
                    other_gesture,
                    bindings=kb_bindings,
                )
            else:
                if self.kb:
                    self.kb.reset()

            # send status
            self._send_status(
                fps=fps,
                cursor_gesture=cursor_gesture,
                other_gesture=other_gesture,
                scroll_active=scroll_active,
                can_mouse=(can_mouse_inject or can_draw_inject or can_ppt_inject),
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
                # OFF: 요청이 있거나 창이 열려있으면 닫기
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

        cap.release()
        cv2.destroyAllWindows()

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

        # ✅ 프론트 표시용: 실제 잠김은 ui_locked OR gesture lock
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
            ),
            "scrollActive": bool(scroll_active),
            "canKey": bool(can_key),
            "otherGesture": str(other_gesture),
            "cursorLandmarks": _lm_to_payload(cursor_lm),
            "otherLandmarks": _lm_to_payload(other_lm),
            "connected": bool(self.ws.connected),
        }

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

        self.ws.send_dict(payload)

        hud = getattr(self.cfg, "hud", None)
        if hud:
            hud_payload = dict(payload)
            hud_payload["connected"] = bool(self.ws.connected)
            hud_payload["tracking"] = bool(payload.get("isTracking", False))
            hud.push(hud_payload)
