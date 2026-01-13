from dataclasses import dataclass, field
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

@dataclass
class KeyboardHandler:
    stable_frames: int = 3
    repeat_sec: float = 0.12
    mod_grace_sec: float = 0.20

    hold_sec: dict = field(default_factory=lambda: {
        "LEFT": 0.10, "RIGHT": 0.10, "UP": 0.10, "DOWN": 0.10,
        "BACKSPACE": 0.12, "SPACE": 0.16, "ENTER": 0.16, "ESC": 0.18,
    })
    cooldown_sec: dict = field(default_factory=lambda: {
        "SPACE": 0.35, "ENTER": 0.35, "ESC": 0.45,
    })

    last_token: str | None = None
    streak: int = 0
    last_repeat_ts: float = 0.0
    last_fire_map: dict = field(default_factory=lambda: {"SPACE": 0.0, "ENTER": 0.0, "ESC": 0.0})
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

    def _press_token(self, token: str):
        keymap = {
            "LEFT": "left", "RIGHT": "right", "UP": "up", "DOWN": "down",
            "BACKSPACE": "backspace", "SPACE": "space", "ENTER": "enter", "ESC": "esc",
        }
        k = keymap.get(token)
        if k:
            pyautogui.press(k)

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

        # FN layer
        if mod_active and got_cursor:
            if cursor_gesture == "FIST":
                token = "BACKSPACE"
            elif cursor_gesture == "OPEN_PALM":
                token = "SPACE"
            elif cursor_gesture == "PINCH_INDEX":
                token = "ENTER"
            elif cursor_gesture == "V_SIGN":
                token = "ESC"

        # base layer
        if token is None and got_cursor:
            if cursor_gesture == "FIST":
                token = "LEFT"
            elif cursor_gesture == "V_SIGN":
                token = "RIGHT"
            elif cursor_gesture == "PINCH_INDEX":
                token = "UP"
            elif cursor_gesture == "OPEN_PALM":
                token = "DOWN"

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

        need_hold = self.hold_sec.get(token, 0.12)
        if (t - self.token_start_ts) < need_hold:
            return

        repeat_tokens = {"LEFT", "RIGHT", "UP", "DOWN", "BACKSPACE"}
        one_shot_tokens = {"SPACE", "ENTER", "ESC"}

        if token in repeat_tokens:
            if t >= self.last_repeat_ts + self.repeat_sec:
                self._press_token(token)
                self.last_repeat_ts = t
            return

        if token in one_shot_tokens:
            if not self.armed:
                return
            cd = self.cooldown_sec.get(token, 0.30)
            last_fire = self.last_fire_map.get(token, 0.0)
            if t < last_fire + cd:
                return
            self._press_token(token)
            self.last_fire_map[token] = t
            self.armed = False
            return
