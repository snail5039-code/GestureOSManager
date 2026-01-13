from dataclasses import dataclass, field
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

@dataclass
class PresentationHandler:
    stable_frames: int = 3
    repeat_sec: float = 0.18
    mod_grace_sec: float = 0.20

    hold_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.10, "PREV": 0.10, "CLICK": 0.10,
        "START": 0.22, "END": 0.22, "BLACK": 0.18, "WHITE": 0.18,
    })
    cooldown_sec: dict = field(default_factory=lambda: {
        "CLICK": 0.25, "START": 0.60, "END": 0.60, "BLACK": 0.45, "WHITE": 0.45,
    })

    last_token: str | None = None
    streak: int = 0
    last_repeat_ts: float = 0.0
    last_fire_map: dict = field(default_factory=lambda: {"CLICK": 0.0, "START": 0.0, "END": 0.0, "BLACK": 0.0, "WHITE": 0.0})
    token_start_ts: float = 0.0
    armed: bool = True
    mod_until: float = 0.0

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.last_repeat_ts = 0.0
        self.token_start_ts = 0.0
        self.armed = True
        self.mod_until = 0.0
        for k in list(self.last_fire_map.keys()):
            self.last_fire_map[k] = 0.0

    def _fire(self, token: str):
        if token == "NEXT":
            pyautogui.press("right")
        elif token == "PREV":
            pyautogui.press("left")
        elif token == "CLICK":
            pyautogui.click()
        elif token == "START":
            pyautogui.press("f5")
        elif token == "END":
            pyautogui.press("esc")
        elif token == "BLACK":
            pyautogui.press("b")
        elif token == "WHITE":
            pyautogui.press("w")

    def update(self, t: float, can_inject: bool,
               got_cursor: bool, cursor_gesture: str,
               got_other: bool, other_gesture: str):
        if not can_inject:
            self.reset()
            return

        if got_other and other_gesture == "PINCH_INDEX":
            self.mod_until = t + self.mod_grace_sec
        mod_active = (t < self.mod_until)

        token = None
        if got_cursor:
            if mod_active:
                if cursor_gesture == "V_SIGN":
                    token = "START"
                elif cursor_gesture == "FIST":
                    token = "END"
                elif cursor_gesture == "OPEN_PALM":
                    token = "BLACK"
                elif cursor_gesture == "PINCH_INDEX":
                    token = "WHITE"
            else:
                if cursor_gesture == "V_SIGN":
                    token = "NEXT"
                elif cursor_gesture == "FIST":
                    token = "PREV"
                elif cursor_gesture == "PINCH_INDEX":
                    token = "CLICK"

        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            return

        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.armed = True
            self.token_start_ts = t

        if self.streak < self.stable_frames:
            return

        need_hold = self.hold_sec.get(token, 0.15)
        if (t - self.token_start_ts) < need_hold:
            return

        repeat_tokens = {"NEXT", "PREV"}
        one_shot_tokens = {"CLICK", "START", "END", "BLACK", "WHITE"}

        if token in repeat_tokens:
            if t >= self.last_repeat_ts + self.repeat_sec:
                self._fire(token)
                self.last_repeat_ts = t
            return

        if token in one_shot_tokens:
            if not self.armed:
                return
            cd = self.cooldown_sec.get(token, 0.35)
            last_fire = self.last_fire_map.get(token, 0.0)
            if t < last_fire + cd:
                return
            self._fire(token)
            self.last_fire_map[token] = t
            self.armed = False
            return
