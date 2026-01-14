import sys
import threading
import time
import math
import ctypes

from gestureos_agent.config import parse_cli
from gestureos_agent.hud_overlay import OverlayHUD
import gestureos_agent.hud_overlay as ho
from gestureos_agent.cursor_system import apply_invisible_cursor, restore_system_cursors
import os

print("[HUD] hud_overlay file =", ho.__file__, flush=True)


from gestureos_agent.agents.hands_agent import HandsAgent
from gestureos_agent.agents.color_rush_agent import ColorRushAgent




def _set_dpi_awareness():
    # Windows DPI scaling (125%/150%)에서도 좌표계 일치시키기
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()   # System DPI aware (fallback)
        except Exception:
            pass

_set_dpi_awareness()

class CfgProxy:
    """frozen dataclass cfg에도 hud를 '추가로' 제공하기 위한 래퍼"""
    def __init__(self, base, hud):
        self._base = base
        self.hud = hud

    def __getattr__(self, name):
        return getattr(self._base, name)

    def get(self, key, default=None):
        b = self._base
        if isinstance(b, dict):
            return b.get(key, default)
        return getattr(b, key, default)

    def __getitem__(self, key):
        b = self._base
        if isinstance(b, dict):
            return b[key]
        return getattr(b, key)


def _hud_test(hud):
    """HUD가 살아있는지 5초만 확인하는 더미 테스트"""
    t0 = time.time()
    while time.time() - t0 < 5:
        t = time.time() - t0
        hud.push({
            "mode": "MOUSE",
            "tracking": True,
            "locked": False,
            "gesture": "TEST",
            "fps": 0.0,
            "connected": True,
            "pointerX": 0.5 + 0.2 * math.sin(t),
            "pointerY": 0.5 + 0.2 * math.cos(t),
        })
        time.sleep(0.016)


def main():
    agent_kind, cfg = parse_cli()

    no_hud = ("--no-hud" in sys.argv)
    hud = OverlayHUD(enable=(not no_hud))
    hud.start()
    
    # OS 커서 숨기기(원할 때만)
    HIDE_OS_CURSOR = True  # 필요하면 False로 끄기

    if HIDE_OS_CURSOR and (not no_hud):
        try:
            cur_path = os.path.join(os.path.dirname(__file__), "gestureos_agent", "assets", "reticle", "invisible.cur")
            apply_invisible_cursor(cur_path)
        except Exception as e:
            print("[CURSOR] hide failed:", e, flush=True)

    try:
        if isinstance(cfg, dict):
            cfg_for_agent = dict(cfg)
            cfg_for_agent["hud"] = hud
        else:
            cfg_for_agent = CfgProxy(cfg, hud)

        if agent_kind == "color":
            ColorRushAgent(cfg_for_agent).run()
        else:
            HandsAgent(cfg_for_agent).run()

    finally:
        if HIDE_OS_CURSOR and (not no_hud):
            try:
                restore_system_cursors()
            except Exception:
                pass
        hud.stop()

if __name__ == "__main__":
    main()
