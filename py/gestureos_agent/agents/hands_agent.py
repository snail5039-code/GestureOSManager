import os
import time
import ctypes
from typing import Any, List, Optional, Tuple

os.environ.setdefault("GLOG_minloglevel", "2")

import cv2
import mediapipe as mp

from ..config import AgentConfig
from ..timeutil import now
from ..gestures import palm_center, classify_gesture
from ..control import ControlMapper
from ..ws_client import WSClient

from ..modes.mouse import MouseClickDrag, MouseRightClick, MouseScroll, MouseLockToggle
from ..modes.keyboard import KeyboardHandler
from ..modes.draw import DrawHandler
from ..modes.presentation import PresentationHandler
from ..modes.vkey import VKeyHandler
from ..modes.ui_menu import UIModeMenu
from ..modes.rush_lr import RushLRPicker
from ..modes.rush_color import ColorStickTracker

# =============================================================================
# OS cursor -> virtual screen normalized (0~1) for HUD reticle alignment
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


# tracking loss handling
LOSS_GRACE_SEC = 0.30
HARD_LOSS_SEC = 0.55
REACQUIRE_BLOCK_SEC = 0.12

# NEXT_MODE event (locked + both OPEN_PALM hold)
MODE_HOLD_SEC = 0.8
MODE_COOLDOWN_SEC = 1.2


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
    """

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

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

        # lock policy
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

        # mode handlers
        self.mouse_click = MouseClickDrag()
        self.mouse_right = MouseRightClick()
        self.mouse_scroll = MouseScroll()
        self.mouse_lock = MouseLockToggle()

        self.kb = KeyboardHandler()
        self.draw = DrawHandler()
        self.ppt = PresentationHandler()
        self.vkey = VKeyHandler()

        self.ui_menu = UIModeMenu()

        # rush handlers
        self.rush_lr = RushLRPicker()
        # (너가 올린 hands_agent.py 전체 코드 그대로…)
        # 중간에 self.rush_color 초기화 부분만 아래처럼 되어 있어야 함:

        self.rush_color = ColorStickTracker(
            s_min=int(os.getenv("RUSH_COLOR_S_MIN", "60")),
            v_min=int(os.getenv("RUSH_COLOR_V_MIN", "60")),
            min_area=int(os.getenv("RUSH_COLOR_MIN_AREA", "220")),
            use_bgr_fallback=(os.getenv("RUSH_COLOR_BGR_FALLBACK", "1") == "1"),
            flip_mirror=(os.getenv("RUSH_COLOR_FLIP", "0") == "1"),
            debug=(os.getenv("RUSH_COLOR_DEBUG", "0") == "1"),
        )

        # -----------------------------------------------------------------
        # 아래는 네가 업로드한 hands_agent.py “전체”를 그대로 출력한 것.
        # 위 초기화 블록이 반영된 버전으로 교체해서 써.
        # -----------------------------------------------------------------


        # tracking loss
        self.last_seen_ts = 0.0
        self.last_cursor_lm = None
        self.last_cursor_cxcy = None
        self.last_cursor_gesture = "NONE"
        self.reacquire_until = 0.0

        # mode menu next_mode
        self.mode_hold_start = None
        self.last_mode_event_ts = 0.0

        # preview window
        self.window_open = False

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

    # ---------- WS helpers ----------
    def send_event(self, name: str, payload: Optional[dict]):
        msg = {"type": "EVENT", "name": name}
        if payload is not None:
            msg["payload"] = payload
        self.ws.send_dict(msg)

    def _on_command(self, data: dict):
        typ = data.get("type")

        # 디버그(지금 단계에서 매우 중요)
        if typ in ("SET_MODE", "ENABLE", "DISABLE", "SET_PREVIEW"):
            print("[PY] cmd:", data, flush=True)

        if typ == "ENABLE":
            self.enabled = True
            self.locked = False

        elif typ == "DISABLE":
            self.enabled = False
            self._reset_side_effects()

        elif typ == "SET_MODE":
            new_mode = str(data.get("mode", "MOUSE")).upper()
            self.apply_set_mode(new_mode)

        elif typ == "SET_PREVIEW":
            self.preview = bool(data.get("enabled", True))

    # ---------- mode + state ----------
    def _reset_side_effects(self):
        self.mouse_click.reset()
        self.mouse_right.reset()
        self.mouse_scroll.reset()

        self.kb.reset()
        self.draw.reset()
        self.ppt.reset()
        self.vkey.reset()

    def apply_set_mode(self, new_mode: str):
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

        self.control.reset_ema()

        if self.mode == "DRAW" and nm != "DRAW":
            self.draw.reset()

        if nm != "MOUSE":
            self.mouse_click.reset()
            self.mouse_right.reset()
            self.mouse_scroll.reset()

        if nm in ("KEYBOARD", "PRESENTATION", "DRAW", "RUSH_HAND", "RUSH_COLOR", "VKEY"):
            self.locked = False

        self.kb.reset()
        self.ppt.reset()
        self.draw.reset()
        self.vkey.reset()

        if nm == "VKEY":
            try:
                self.vkey.open_windows_osk()
            except Exception:
                pass

        self.mode = nm
        print("[PY] apply_set_mode ->", self.mode, flush=True)

    # ---------- capture ----------
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

    # ---------- main loop ----------
    def run(self):
        print("[PY] running:", os.path.abspath(__file__), flush=True)
        print("[PY] WS_URL:", getattr(self.cfg, "ws_url", ""), "(disabled)" if getattr(self.cfg, "no_ws", False) else "", flush=True)

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
            rush_left, rush_right = self.rush_lr.pick(t, hands_list)

            # RUSH_COLOR: override with HSV stick tracking
            if str(self.mode).upper() == "RUSH_COLOR":
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
                    for label, lm in hands_list:
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

            # UI menu (HUD)
            _ = self.ui_menu.update(
                t=t,
                enabled=self.enabled,
                mode=self.mode,
                cursor_gesture=cursor_gesture,
                other_gesture=other_gesture,
                got_other=got_other,
                send_event=lambda name, payload: self.send_event(name, payload),
            )

            # NEXT_MODE when locked: both OPEN_PALM hold
            if self.enabled and self.locked and got_other and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM"):
                if self.mode_hold_start is None:
                    self.mode_hold_start = t
                if (t - self.mode_hold_start) >= MODE_HOLD_SEC and t >= (self.last_mode_event_ts + MODE_COOLDOWN_SEC):
                    self.send_event("NEXT_MODE", None)
                    self.last_mode_event_ts = t
                    self.mode_hold_start = None
            else:
                self.mode_hold_start = None

            # LOCK only in MOUSE
            if mode_u == "MOUSE":
                self.locked = self.mouse_lock.update(
                    t=t,
                    cursor_gesture=cursor_gesture,
                    cx=cursor_cx,
                    cy=cursor_cy,
                    got_cursor=got_cursor,
                    got_other=got_other,
                    enabled=self.enabled,
                    locked=self.locked,
                )
            else:
                self.mouse_lock.reset()

            # injection permissions
            no_inject = bool(getattr(self.cfg, "no_inject", False))
            can_mouse_inject = self.enabled and (mode_u == "MOUSE") and (t >= self.reacquire_until) and (not self.locked) and (not no_inject)
            can_draw_inject  = self.enabled and (mode_u == "DRAW") and (t >= self.reacquire_until) and (not self.locked) and (not no_inject)
            can_kb_inject    = self.enabled and (mode_u == "KEYBOARD") and (t >= self.reacquire_until) and (not self.locked) and (not no_inject)
            can_ppt_inject   = self.enabled and (mode_u == "PRESENTATION") and (t >= self.reacquire_until) and (not self.locked) and (not no_inject)
            can_vkey_detect  = self.enabled and (mode_u == "VKEY") and (t >= self.reacquire_until) and (not self.locked)
            can_vkey_click   = can_vkey_detect and (not no_inject)

            # RUSH disables OS inject
            if mode_u.startswith("RUSH"):
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False
                can_vkey_detect = False
                can_vkey_click = False

            # VKEY uses only vkey
            if mode_u == "VKEY":
                can_mouse_inject = False
                can_draw_inject = False
                can_kb_inject = False
                can_ppt_inject = False

            # pointer move
            can_pointer_inject = (can_mouse_inject or can_draw_inject or can_ppt_inject)
            if can_pointer_inject and got_cursor:
                do_move = False
                if mode_u == "MOUSE":
                    do_move = (cursor_gesture == "OPEN_PALM") or (self.mouse_click.dragging and cursor_gesture == "PINCH_INDEX")
                elif mode_u == "DRAW":
                    do_move = (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX")) or self.draw.down
                elif mode_u == "PRESENTATION":
                    do_move = (cursor_gesture == "OPEN_PALM")

                if do_move:
                    ux, uy = self.control.map_control_to_screen(cursor_cx, cursor_cy)
                    ex, ey = self.control.apply_ema(ux, uy)
                    self.control.move_cursor(ex, ey, t)

            # mouse actions
            if mode_u == "MOUSE":
                self.mouse_click.update(t, cursor_gesture, can_mouse_inject)
                self.mouse_right.update(t, cursor_gesture, can_mouse_inject)
            else:
                self.mouse_click.update(t, cursor_gesture, False)
                self.mouse_right.update(t, cursor_gesture, False)

            # draw
            if mode_u == "DRAW":
                self.draw.update_draw(t, cursor_gesture, can_draw_inject)
                self.draw.update_selection_shortcuts(t, cursor_gesture, other_gesture, got_other, can_draw_inject)
            else:
                self.draw.reset()

            # presentation
            if mode_u == "PRESENTATION":
                self.ppt.update(t, can_ppt_inject, got_cursor, cursor_gesture, got_other, other_gesture)
            else:
                self.ppt.reset()

            # scroll (mouse only)
            scroll_active = False
            if can_mouse_inject and got_other:
                self.mouse_scroll.update(t, other_gesture == "FIST", other_cy, True)
                scroll_active = (other_gesture == "FIST")
            else:
                self.mouse_scroll.update(t, False, 0.5, False)

            # keyboard
            self.kb.update(t, can_kb_inject, got_cursor, cursor_gesture, got_other, other_gesture)

            # vkey
            if mode_u == "VKEY":
                self.vkey.update(t, can_vkey_click, cursor_lm, self.control.map_control_to_screen)

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
            if bool(getattr(self.cfg, "headless", False)):
                time.sleep(0.001)
                continue

            if self.preview:
                if not self.window_open:
                    cv2.namedWindow("GestureOS Agent", cv2.WINDOW_NORMAL)
                    self.window_open = True

                lp = _pack_xy(rush_left)
                rp = _pack_xy(rush_right)

                line1 = f"mode={mode_u} enabled={self.enabled} locked={self.locked} cur={cursor_gesture} oth={other_gesture}"
                cv2.putText(frame, line1, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

                if lp is not None:
                    cv2.putText(frame, f"RUSH L: ({lp[0]:.2f},{lp[1]:.2f})", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
                if rp is not None:
                    cv2.putText(frame, f"RUSH R: ({rp[0]:.2f},{rp[1]:.2f})", (10, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)

                cv2.imshow("GestureOS Agent", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break

        cap.release()
        cv2.destroyAllWindows()

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

        payload = {
            "type": "STATUS",
            "enabled": bool(self.enabled),
            "mode": mode_u,  # ✅ 절대 RUSH로 뭉개지 말 것 (RUSH_HAND/RUSH_COLOR 그대로)
            "locked": bool(self.locked),
            "preview": bool(self.preview),

            "gesture": str(cursor_gesture),
            "fps": float(fps),

            "canMove": bool(can_mouse and (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX"))),
            "canClick": bool((can_mouse and (cursor_gesture in ("PINCH_INDEX", "V_SIGN"))) or (self.enabled and mode_u == "VKEY")),
            "scrollActive": bool(scroll_active),
            "canKey": bool(can_key),

            "otherGesture": str(other_gesture),

            "cursorLandmarks": _lm_to_payload(cursor_lm),
            "otherLandmarks": _lm_to_payload(other_lm),

            "tapSeq": int(getattr(self.vkey, "tap_seq", 0)),
            "connected": bool(self.ws.connected),
        }

        # 러쉬 입력 타입 제공(서버/프론트 표시용)
        if mode_u.startswith("RUSH"):
            payload["rushInput"] = "COLOR" if mode_u == "RUSH_COLOR" else "HAND"

        # pointer
        payload["pointerX"] = None
        payload["pointerY"] = None
        payload["isTracking"] = False

        # left/right packs
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

        # pointer 결정(단 한 번)
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
