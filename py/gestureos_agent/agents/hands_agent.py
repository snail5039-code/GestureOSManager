import json
import os
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

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

class HandsAgent:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

        self.enabled = bool(cfg.start_enabled)
        self.mode = "MOUSE"
        if cfg.start_keyboard:
            self.mode = "KEYBOARD"
        elif cfg.start_rush:
            self.mode = "RUSH"
        elif cfg.start_vkey:
            self.mode = "VKEY"

        # lock policy: start locked unless enabled, but most modes unlock for usability
        self.locked = True
        if self.enabled:
            self.locked = False
        if self.mode in ("KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY"):
            self.locked = False

        self.preview = (not cfg.headless)

        self.cursor_hand_label = "Left" if cfg.force_cursor_left else "Right"

        self.control = ControlMapper(
            control_box=cfg.control_box,
            gain=cfg.control_gain,
            ema_alpha=cfg.ema_alpha,
            deadzone_px=cfg.deadzone_px,
            move_interval_sec=(1.0 / max(1e-6, cfg.move_hz)),
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
        self.rush_lr = RushLRPicker()

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
        self.ws = WSClient(cfg.ws_url, self._on_command, enabled=(not cfg.no_ws))

    # ---------- WS helpers ----------
    def send_event(self, name: str, payload: Optional[dict]):
        if self.cfg.no_ws:
            return
        msg = {"type": "EVENT", "name": name}
        if payload is not None:
            msg["payload"] = payload
        self.ws.send_dict(msg)

    def _on_command(self, data: dict):
        typ = data.get("type")

        if typ == "ENABLE":
            self.enabled = True
            self.locked = False
            print("[PY] cmd ENABLE -> enabled=True")

        elif typ == "DISABLE":
            self.enabled = False
            self._reset_side_effects()
            print("[PY] cmd DISABLE -> enabled=False")

        elif typ == "SET_MODE":
            new_mode = str(data.get("mode", "MOUSE")).upper()
            self.apply_set_mode(new_mode)

        elif typ == "SET_PREVIEW":
            self.preview = bool(data.get("enabled", True))
            print("[PY] cmd SET_PREVIEW ->", self.preview)

    # ---------- mode + state ----------
    def _reset_side_effects(self):
        # mouse drag/click internal states
        self.mouse_click.reset()
        self.mouse_right.reset()
        self.mouse_scroll.reset()

        # per-mode states
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

        allowed = {"MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY"}
        if nm not in allowed:
            print("[PY] apply_set_mode ignored:", new_mode)
            return

        # reset EMA
        self.control.reset_ema()

        # leaving draw => ensure mouseUp
        if self.mode == "DRAW" and nm != "DRAW":
            self.draw.reset()

        # leaving mouse => release drag if any
        if nm != "MOUSE":
            self.mouse_click.reset()
            self.mouse_right.reset()
            self.mouse_scroll.reset()

        # entering: unlock convenience
        if nm in ("KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY"):
            self.locked = False

        # reset mode handlers when switching
        self.kb.reset()
        self.ppt.reset()
        self.draw.reset()
        self.vkey.reset()

        if nm == "VKEY":
            self.vkey.open_windows_osk()

        self.mode = nm
        print("[PY] apply_set_mode ->", self.mode)

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
        print("[PY] running:", os.path.abspath(__file__))
        print("[PY] WS_URL:", self.cfg.ws_url, "(disabled)" if self.cfg.no_ws else "")
        print("[PY] CURSOR_HAND_LABEL:", self.cursor_hand_label)
        print("[PY] NO_INJECT:", self.cfg.no_inject)

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

            # rush left/right packs
            rush_left, rush_right = self.rush_lr.pick(t, hands_list)

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
            ui_consuming = self.ui_menu.update(
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
            can_mouse_inject = self.enabled and (mode_u == "MOUSE") and (t >= self.reacquire_until) and (not self.locked) and (not self.cfg.no_inject)
            can_draw_inject  = self.enabled and (mode_u == "DRAW") and (t >= self.reacquire_until) and (not self.locked) and (not self.cfg.no_inject)
            can_kb_inject    = self.enabled and (mode_u == "KEYBOARD") and (t >= self.reacquire_until) and (not self.locked) and (not self.cfg.no_inject)
            can_ppt_inject   = self.enabled and (mode_u == "PRESENTATION") and (t >= self.reacquire_until) and (not self.locked) and (not self.cfg.no_inject)
            can_vkey_detect  = self.enabled and (mode_u == "VKEY") and (t >= self.reacquire_until) and (not self.locked)  # detection even if no_inject
            can_vkey_click   = can_vkey_detect and (not self.cfg.no_inject)

            # RUSH disables OS inject
            if mode_u == "RUSH":
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
            )

            # preview keys
            if self.cfg.headless:
                time.sleep(0.001)
                continue

            if self.preview:
                if not self.window_open:
                    cv2.namedWindow("GestureOS Agent", cv2.WINDOW_NORMAL)
                    self.window_open = True

                fn_on = (t < self.kb.mod_until) or (t < self.ppt.mod_until)
                line1 = f"mode={mode_u} enabled={self.enabled} locked={self.locked} cur={cursor_gesture} oth={other_gesture} FN={fn_on} noInject={self.cfg.no_inject}"
                cv2.putText(frame, line1, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

                if mode_u == "VKEY":
                    cv2.putText(frame, "VKEY: Multi-finger AirTap (4/8/12/16/20)", (10, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
                    cv2.putText(frame, f"tapSeq={self.vkey.tap_seq}", (10, 75),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)

                if rush_left is not None:
                    cv2.putText(frame, f"RUSH L: ({rush_left['cx']:.2f},{rush_left['cy']:.2f}) {rush_left['gesture']}",
                                (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
                if rush_right is not None:
                    cv2.putText(frame, f"RUSH R: ({rush_right['cx']:.2f},{rush_right['cy']:.2f}) {rush_right['gesture']}",
                                (10, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)

                cv2.imshow("GestureOS Agent", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                elif key in (ord('e'), ord('E')):
                    self.enabled = not self.enabled
                    if not self.enabled:
                        self._reset_side_effects()
                    print("[KEY] enabled:", self.enabled)
                elif key in (ord('l'), ord('L')):
                    self.locked = not self.locked
                    print("[KEY] locked:", self.locked)
                elif key in (ord('p'), ord('P')):
                    self.preview = not self.preview
                    print("[KEY] preview:", self.preview)
                elif key in (ord('m'), ord('M')):
                    self.apply_set_mode("MOUSE")
                elif key in (ord('k'), ord('K')):
                    self.apply_set_mode("KEYBOARD")
                elif key in (ord('r'), ord('R')):
                    self.apply_set_mode("RUSH")
                elif key in (ord('v'), ord('V')):
                    self.apply_set_mode("VKEY")
                elif key in (ord('o'), ord('O')):
                    self.vkey.open_windows_osk()
                    print("[KEY] open OSK")
                elif key in (ord('c'), ord('C')):
                    # calibrate control box around current cursor center
                    cx, cy = self.last_cursor_cxcy if self.last_cursor_cxcy is not None else (0.5, 0.5)
                    from ..mathutil import clamp01
                    minx = clamp01(cx - self.cfg.control_half_w)
                    maxx = clamp01(cx + self.cfg.control_half_w)
                    miny = clamp01(cy - self.cfg.control_half_h)
                    maxy = clamp01(cy + self.cfg.control_half_h)
                    self.control.control_box = (minx, miny, maxx, maxy)
                    self.control.reset_ema()
                    print("[CALIB] CONTROL_BOX =", self.control.control_box)
            else:
                if self.window_open:
                    cv2.destroyWindow("GestureOS Agent")
                    self.window_open = False
                time.sleep(0.005)

        cap.release()
        cv2.destroyAllWindows()

    def _send_status(self, fps: float, cursor_gesture: str, other_gesture: str,
                     scroll_active: bool, can_mouse: bool, can_key: bool,
                     rush_left, rush_right, cursor_lm, other_lm):
        if self.cfg.no_ws:
            return

        mode_u = str(self.mode).upper()
        payload = {
            "type": "STATUS",
            "enabled": bool(self.enabled),
            "mode": str(self.mode),
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

            # AirTap
            "tapSeq": int(self.vkey.tap_seq),
        }

        if self.vkey.last_tap is not None:
            payload["tapX"] = float(self.vkey.last_tap["x"])
            payload["tapY"] = float(self.vkey.last_tap["y"])
            payload["tapFinger"] = int(self.vkey.last_tap["finger"])
            payload["tapTs"] = float(self.vkey.last_tap["ts"])

        # RUSH packs
        if rush_left is not None:
            payload["leftPointerX"] = float(rush_left["cx"])
            payload["leftPointerY"] = float(rush_left["cy"])
            payload["leftTracking"] = True
            payload["leftGesture"] = str(rush_left.get("gesture", "NONE"))
        else:
            payload["leftTracking"] = False

        if rush_right is not None:
            payload["rightPointerX"] = float(rush_right["cx"])
            payload["rightPointerY"] = float(rush_right["cy"])
            payload["rightTracking"] = True
            payload["rightGesture"] = str(rush_right.get("gesture", "NONE"))
        else:
            payload["rightTracking"] = False

        # fallback pointer
        if rush_right is not None:
            payload["pointerX"] = float(rush_right["cx"])
            payload["pointerY"] = float(rush_right["cy"])
            payload["isTracking"] = True
        elif rush_left is not None:
            payload["pointerX"] = float(rush_left["cx"])
            payload["pointerY"] = float(rush_left["cy"])
            payload["isTracking"] = True
        elif mode_u == "VKEY" and cursor_lm is not None:
            payload["pointerX"] = float(cursor_lm[8][0])
            payload["pointerY"] = float(cursor_lm[8][1])
            payload["isTracking"] = True
        else:
            payload["isTracking"] = False

        self.ws.send_dict(payload)
