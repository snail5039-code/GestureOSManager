import os
import sys
import time
import math
import ctypes
from dataclasses import replace

from gestureos_agent.config import parse_cli
from gestureos_agent.hud_overlay import OverlayHUD
import gestureos_agent.hud_overlay as ho

from gestureos_agent.cursor_system import apply_invisible_cursor, restore_system_cursors
from gestureos_agent.agents.hands_agent import HandsAgent


print("[HUD] hud_overlay file =", ho.__file__, flush=True)


def _set_dpi_awareness():
    # Windows DPI scaling에서도 좌표계 일치시키기
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # fallback
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


def main():
    agent_kind, cfg = parse_cli()

    # Backward-compat: --agent=color -> start RUSH_COLOR
    if agent_kind == "color":
        cfg = replace(cfg, start_rush=True, rush_input="COLOR")

    no_hud = ("--no-hud" in sys.argv)

    hud = OverlayHUD(enable=(not no_hud))
    hud.start()

    # OS 커서 숨기기(원할 때만)
    HIDE_OS_CURSOR = True
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
