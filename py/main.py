import sys
import threading
import time
import math

from gestureos_agent.config import parse_cli
from gestureos_agent.hud_overlay import OverlayHUD

from gestureos_agent.agents.hands_agent import HandsAgent
from gestureos_agent.agents.color_rush_agent import ColorRushAgent


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

    # ✅ 더미 테스트(확인 끝나면 지워도 됨)
    threading.Thread(target=_hud_test, args=(hud,), daemon=True).start()

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
        hud.stop()


if __name__ == "__main__":
    main()
