from dataclasses import dataclass

@dataclass
class UIModeMenu:
    open_hold_sec: float = 0.60
    close_hold_sec: float = 0.30
    confirm_hold_sec: float = 0.25
    timeout_sec: float = 5.0
    open_cooldown_sec: float = 1.0
    nav_cooldown_sec: float = 0.22

    open_start: float | None = None
    close_start: float | None = None
    confirm_start: float | None = None

    active: bool = False
    until: float = 0.0
    last_open_ts: float = 0.0
    last_nav_ts: float = 0.0

    next_armed: bool = True
    prev_armed: bool = True

    def reset(self):
        self.open_start = None
        self.close_start = None
        self.confirm_start = None
        self.active = False
        self.until = 0.0
        self.last_open_ts = 0.0
        self.last_nav_ts = 0.0
        self.next_armed = True
        self.prev_armed = True

    def update(self, t: float, enabled: bool, mode: str,
               cursor_gesture: str, other_gesture: str, got_other: bool,
               send_event) -> bool:
        """
        Returns: consume(bool) - when menu is active, always consumes.
        send_event(name, payload)
        """
        # disabled => force close
        if not enabled:
            if self.active:
                self.active = False
                send_event("MODE_MENU_CLOSE", None)
            self.open_start = None
            self.close_start = None
            self.confirm_start = None
            return False

        # closed state: open detect (both FIST hold)
        if not self.active:
            both_fist = got_other and (cursor_gesture == "FIST") and (other_gesture == "FIST")
            if both_fist:
                if self.open_start is None:
                    self.open_start = t
                if (t - self.open_start) >= self.open_hold_sec and t >= (self.last_open_ts + self.open_cooldown_sec):
                    self.active = True
                    self.until = t + self.timeout_sec
                    self.last_open_ts = t
                    self.open_start = None
                    self.close_start = None
                    self.confirm_start = None
                    self.last_nav_ts = 0.0
                    self.next_armed = True
                    self.prev_armed = True
                    send_event("OPEN_MODE_MENU", {"mode": str(mode).upper()})
                    return True
            else:
                self.open_start = None
            return False

        # active state timeout
        if t >= self.until:
            self.active = False
            send_event("MODE_MENU_CLOSE", None)
            self.close_start = None
            self.confirm_start = None
            return False

        consume = True

        # close: both FIST hold
        both_fist = got_other and (cursor_gesture == "FIST") and (other_gesture == "FIST")
        if both_fist:
            if self.close_start is None:
                self.close_start = t
            if (t - self.close_start) >= self.close_hold_sec:
                self.active = False
                send_event("MODE_MENU_CLOSE", None)
                self.close_start = None
                self.confirm_start = None
                return True
        else:
            self.close_start = None

        # confirm: both OPEN_PALM hold
        both_open = got_other and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM")
        if both_open:
            if self.confirm_start is None:
                self.confirm_start = t
            if (t - self.confirm_start) >= self.confirm_hold_sec:
                self.active = False
                send_event("MODE_MENU_CONFIRM", None)
                self.confirm_start = None
                self.close_start = None
                return True
        else:
            self.confirm_start = None

        # nav edge + cooldown
        if cursor_gesture != "PINCH_INDEX":
            self.next_armed = True
        if cursor_gesture != "V_SIGN":
            self.prev_armed = True

        if cursor_gesture == "PINCH_INDEX" and self.next_armed and t >= (self.last_nav_ts + self.nav_cooldown_sec):
            send_event("MODE_MENU_NEXT", None)
            self.last_nav_ts = t
            self.next_armed = False
            self.until = t + self.timeout_sec
            return True

        if cursor_gesture == "V_SIGN" and self.prev_armed and t >= (self.last_nav_ts + self.nav_cooldown_sec):
            send_event("MODE_MENU_PREV", None)
            self.last_nav_ts = t
            self.prev_armed = False
            self.until = t + self.timeout_sec
            return True

        return consume
