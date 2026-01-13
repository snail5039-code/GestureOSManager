from dataclasses import dataclass
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

@dataclass
class DrawHandler:
    down_debounce_sec: float = 0.04
    sel_hold_sec: float = 0.28
    sel_cooldown_sec: float = 0.60

    pinch_start_ts: float | None = None
    down: bool = False

    copy_hold: float | None = None
    last_copy_ts: float = 0.0
    copy_fired: bool = False

    cut_hold: float | None = None
    last_cut_ts: float = 0.0
    cut_fired: bool = False

    def reset(self):
        self.pinch_start_ts = None
        if self.down:
            try:
                pyautogui.mouseUp()
            except Exception:
                pass
        self.down = False

        self.copy_hold = None
        self.copy_fired = False
        self.cut_hold = None
        self.cut_fired = False

    def update_draw(self, t: float, cursor_gesture: str, can_inject: bool):
        if not can_inject:
            self.reset()
            return

        if cursor_gesture == "PINCH_INDEX":
            if self.pinch_start_ts is None:
                self.pinch_start_ts = t
            if (not self.down) and ((t - self.pinch_start_ts) >= self.down_debounce_sec):
                pyautogui.mouseDown()
                self.down = True
        else:
            self.pinch_start_ts = None
            if self.down:
                pyautogui.mouseUp()
                self.down = False

    def update_selection_shortcuts(self, t: float,
                                  cursor_gesture: str,
                                  other_gesture: str,
                                  got_other: bool,
                                  can_inject: bool):
        if not can_inject:
            self.copy_hold = None
            self.copy_fired = False
            self.cut_hold = None
            self.cut_fired = False
            return

        mod = got_other and (other_gesture == "PINCH_INDEX")

        # Ctrl+C: mod + cursor V_SIGN hold
        if mod and (cursor_gesture == "V_SIGN"):
            if t < self.last_copy_ts + self.sel_cooldown_sec:
                self.copy_hold = None
                self.copy_fired = False
            else:
                if not self.copy_fired:
                    if self.copy_hold is None:
                        self.copy_hold = t
                    elif (t - self.copy_hold) >= self.sel_hold_sec:
                        pyautogui.hotkey("ctrl", "c")
                        self.last_copy_ts = t
                        self.copy_fired = True
        else:
            self.copy_hold = None
            self.copy_fired = False

        # Ctrl+X: mod + cursor FIST hold
        if mod and (cursor_gesture == "FIST"):
            if t < self.last_cut_ts + self.sel_cooldown_sec:
                self.cut_hold = None
                self.cut_fired = False
            else:
                if not self.cut_fired:
                    if self.cut_hold is None:
                        self.cut_hold = t
                    elif (t - self.cut_hold) >= self.sel_hold_sec:
                        pyautogui.hotkey("ctrl", "x")
                        self.last_cut_ts = t
                        self.cut_fired = True
        else:
            self.cut_hold = None
            self.cut_fired = False
