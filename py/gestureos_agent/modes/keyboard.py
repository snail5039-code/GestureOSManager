from dataclasses import dataclass, field

import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


@dataclass
class KeyboardHandler:
    """KEYBOARD mode 입력(연발 억제 버전)

    정책:
    - 화살표/백스페이스도 기본은 "단발 1회"만 발동
    - 같은 제스처를 충분히 오래 유지(repeat_start_sec)했을 때만 느린 반복(repeat_sec) 허용
    - SPACE/ENTER/ESC 는 단발(armed + cooldown)
    """

    stable_frames: int = 3

    # repeat: "길게 들고 있을 때만" 천천히 반복
    repeat_start_sec: float = 0.55
    repeat_sec: float = 0.22

    mod_grace_sec: float = 0.20

    hold_sec: dict = field(
        default_factory=lambda: {
            "LEFT": 0.12,
            "RIGHT": 0.12,
            "UP": 0.12,
            "DOWN": 0.12,
            "BACKSPACE": 0.14,
            "SPACE": 0.16,
            "ENTER": 0.16,
            "ESC": 0.18,
        }
    )

    # 모든 토큰에 쿨다운을 줘서 손떨림/토큰 흔들림으로 인한 연속 발동 억제
    cooldown_sec: dict = field(
        default_factory=lambda: {
            "LEFT": 0.22,
            "RIGHT": 0.22,
            "UP": 0.22,
            "DOWN": 0.22,
            "BACKSPACE": 0.25,
            "SPACE": 0.35,
            "ENTER": 0.35,
            "ESC": 0.45,
        }
    )

    last_token: str | None = None
    streak: int = 0
    token_start_ts: float = 0.0

    # one-shot gating
    armed: bool = True

    # repeat gating
    pressed_once: bool = False
    repeat_start_ts: float = 0.0
    last_repeat_ts: float = 0.0

    # per-token cooldown tracking
    last_fire_map: dict = field(
        default_factory=lambda: {
            "LEFT": 0.0,
            "RIGHT": 0.0,
            "UP": 0.0,
            "DOWN": 0.0,
            "BACKSPACE": 0.0,
            "SPACE": 0.0,
            "ENTER": 0.0,
            "ESC": 0.0,
        }
    )

    mod_until: float = 0.0

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.token_start_ts = 0.0
        self.armed = True
        self.pressed_once = False
        self.repeat_start_ts = 0.0
        self.last_repeat_ts = 0.0
        self.mod_until = 0.0
        for k in list(self.last_fire_map.keys()):
            self.last_fire_map[k] = 0.0

    def _press_token(self, token: str):
        keymap = {
            "LEFT": "left",
            "RIGHT": "right",
            "UP": "up",
            "DOWN": "down",
            "BACKSPACE": "backspace",
            "SPACE": "space",
            "ENTER": "enter",
            "ESC": "esc",
        }
        k = keymap.get(token)
        if k:
            pyautogui.press(k)

    def update(
        self,
        t: float,
        can_inject: bool,
        got_cursor: bool,
        cursor_gesture: str,
        got_other: bool,
        other_gesture: str,
    ):
        if not can_inject:
            self.reset()
            return

        # FN(mod) layer: other hand PINCH_INDEX briefly enables
        if got_other and other_gesture == "PINCH_INDEX":
            self.mod_until = t + self.mod_grace_sec
        mod_active = t < self.mod_until

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

        # no token => re-arm and clear repeat state
        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            self.pressed_once = False
            self.repeat_start_ts = 0.0
            return

        # stability tracking + state reset on token change
        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.armed = True
            self.pressed_once = False
            self.repeat_start_ts = 0.0
            self.token_start_ts = t

        if self.streak < self.stable_frames:
            return

        need_hold = self.hold_sec.get(token, 0.12)
        if (t - self.token_start_ts) < need_hold:
            return

        repeat_tokens = {"LEFT", "RIGHT", "UP", "DOWN", "BACKSPACE"}
        one_shot_tokens = {"SPACE", "ENTER", "ESC"}

        cd = self.cooldown_sec.get(token, 0.25)
        last_fire = self.last_fire_map.get(token, 0.0)
        if t < last_fire + cd:
            return

        # repeatable tokens: first press once, then (if held) slow repeat
        if token in repeat_tokens:
            if not self.pressed_once:
                self._press_token(token)
                self.last_fire_map[token] = t
                self.pressed_once = True
                self.repeat_start_ts = t
                self.last_repeat_ts = t
                return

            # allow repeating only after long hold
            if (t - self.repeat_start_ts) < self.repeat_start_sec:
                return
            if t >= self.last_repeat_ts + self.repeat_sec:
                self._press_token(token)
                self.last_fire_map[token] = t
                self.last_repeat_ts = t
            return

        # one-shot tokens: strict armed gating
        if token in one_shot_tokens:
            if not self.armed:
                return
            self._press_token(token)
            self.last_fire_map[token] = t
            self.armed = False
            return
