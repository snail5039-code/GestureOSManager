from dataclasses import dataclass, field
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


@dataclass
class PresentationHandler:
    """
    PRESENTATION mode (단발 + 인터랙션 레이어)

    기본(네비게이션):
      - 양손 OPEN_PALM     : F5  (슬라이드쇼 시작)
      - PINCH_INDEX        : →   (다음 슬라이드)
      - V_SIGN             : ←   (이전 슬라이드)
      - 양손 PINCH_INDEX    : ESC (슬라이드쇼 종료)

    인터랙션(핫스팟/하이퍼링크/비디오) 모드:
      - 조건: 다른 손(other)이 FIST일 때만 활성화
      - V_SIGN             : Tab       (다음 핫스팟 포커스)
      - FIST               : Shift+Tab (이전 핫스팟 포커스)
      - PINCH_INDEX        : Enter     (실행/열기)
      - OPEN_PALM          : Alt+P     (재생/일시정지 - 환경 따라 제한 가능)
    """

    stable_frames: int = 3

    hold_sec: dict = field(default_factory=lambda: {
        # navigation
        "NEXT": 0.08,
        "PREV": 0.08,
        "START": 0.20,
        "END": 0.20,

        # interaction
        "TAB": 0.08,
        "SHIFT_TAB": 0.08,
        "ACTIVATE": 0.10,
        "PLAY_PAUSE": 0.12,
    })

    cooldown_sec: dict = field(default_factory=lambda: {
        # navigation
        "NEXT": 0.30,
        "PREV": 0.30,
        "START": 0.80,
        "END": 0.80,

        # interaction
        "TAB": 0.25,
        "SHIFT_TAB": 0.25,
        "ACTIVATE": 0.40,
        "PLAY_PAUSE": 0.60,
    })

    last_token: str | None = None
    streak: int = 0
    token_start_ts: float = 0.0
    armed: bool = True

    last_fire_map: dict = field(default_factory=lambda: {
        "NEXT": 0.0, "PREV": 0.0, "START": 0.0, "END": 0.0,
        "TAB": 0.0, "SHIFT_TAB": 0.0, "ACTIVATE": 0.0, "PLAY_PAUSE": 0.0,
    })

    # hands_agent에서 FN 표시할 때 접근함(호환용). 여기선 안 씀.
    mod_until: float = 0.0

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.token_start_ts = 0.0
        self.armed = True
        self.mod_until = 0.0
        for k in list(self.last_fire_map.keys()):
            self.last_fire_map[k] = 0.0

    def _fire(self, token: str):
        # === navigation ===
        if token == "NEXT":
            pyautogui.press("right")
        elif token == "PREV":
            pyautogui.press("left")
        elif token == "START":
            pyautogui.press("f5")
        elif token == "END":
            pyautogui.press("esc")

        # === interaction ===
        elif token == "TAB":
            pyautogui.press("tab")
        elif token == "SHIFT_TAB":
            pyautogui.hotkey("shift", "tab")
        elif token == "ACTIVATE":
            pyautogui.press("enter")
        elif token == "PLAY_PAUSE":
            pyautogui.hotkey("alt", "p")

    def update(self, t: float, can_inject: bool,
               got_cursor: bool, cursor_gesture: str,
               got_other: bool, other_gesture: str):
        if not can_inject:
            self.reset()
            return

        # 안전: KNIFE 오인식은 OPEN_PALM처럼 처리
        if cursor_gesture == "KNIFE":
            cursor_gesture = "OPEN_PALM"
        if other_gesture == "KNIFE":
            other_gesture = "OPEN_PALM"

        token = None

        # 2손 제스처 우선 (START/END)
        if got_cursor and got_other:
            if cursor_gesture == "PINCH_INDEX" and other_gesture == "PINCH_INDEX":
                token = "END"
            elif cursor_gesture == "OPEN_PALM" and other_gesture == "OPEN_PALM":
                token = "START"

        # 인터랙션 모드: 다른 손이 FIST일 때만
        interaction_mode = (got_other and other_gesture == "FIST")

        # 1손 제스처
        if token is None and got_cursor:
            if interaction_mode:
                # 핫스팟(링크/비디오) 조작
                if cursor_gesture == "V_SIGN":
                    token = "TAB"
                elif cursor_gesture == "FIST":
                    token = "SHIFT_TAB"
                elif cursor_gesture == "PINCH_INDEX":
                    token = "ACTIVATE"
                elif cursor_gesture == "OPEN_PALM":
                    token = "PLAY_PAUSE"
            else:
                # 기본 슬라이드 네비게이션
                if cursor_gesture == "PINCH_INDEX":
                    token = "NEXT"
                elif cursor_gesture == "V_SIGN":
                    token = "PREV"

        # 토큰 없으면 재무장
        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            return

        # 안정화 프레임
        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.armed = True
            self.token_start_ts = t

        if self.streak < self.stable_frames:
            return

        # 홀드 시간
        need_hold = self.hold_sec.get(token, 0.12)
        if (t - self.token_start_ts) < need_hold:
            return

        # 단발 + 쿨다운
        if not self.armed:
            return

        cd = self.cooldown_sec.get(token, 0.30)
        last_fire = self.last_fire_map.get(token, 0.0)
        if t < last_fire + cd:
            return

        self._fire(token)
        self.last_fire_map[token] = t
        self.armed = False
