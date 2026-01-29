# py/gestureos_agent/_draw_state.py
"""
Shared state for DRAW mode pen-hold.

Why:
- Win11에서 SendInput으로 LEFTDOWN을 쏘더라도 GetAsyncKeyState(VK_LBUTTON)이
  앱/타이밍에 따라 즉시 반영되지 않는 경우가 있어 DRAW 전용 move 튜닝이
  적용되지 않으면서 스트로크가 끊겨 보일 수 있음.
- DRAW 핸들러가 '현재 pen-hold(왼쪽 버튼 홀드)' 상태를 명시적으로 공유한다.
"""

from __future__ import annotations
import time
import threading

_lock = threading.Lock()
_down = False
_down_ts = 0.0

def set_down(v: bool) -> None:
    global _down, _down_ts
    with _lock:
        _down = bool(v)
        if _down:
            _down_ts = time.time()
        else:
            _down_ts = 0.0

def is_down() -> bool:
    with _lock:
        return bool(_down)

def down_age_sec(now: float | None = None) -> float:
    with _lock:
        if not _down or _down_ts <= 0:
            return 0.0
        t = now if now is not None else time.time()
        return max(0.0, t - _down_ts)
