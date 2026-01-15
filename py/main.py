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
from gestureos_agent.agents.color_rush_agent import ColorRushAgent
from gestureos_agent.ws_client import WSClient


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
    
    # --- HUD control WS: ws://.../ws/hud ---
    def _on_hud_cmd(msg: dict):
        t = str(msg.get("type", "")).upper()

        if t == "SET_VISIBLE":
            hud.set_overlay_visible(bool(msg.get("enabled", True)))

        elif t == "SET_HUD_VISIBLE":
            hud.set_hud_visible(bool(msg.get("enabled", True)))

        elif t == "SET_HUD_POS":
            hud.set_hud_position(
                msg.get("x", 20),
                msg.get("y", 20),
                normalized=bool(msg.get("normalized", False)),
            )

        elif t == "NUDGE_HUD":
            hud.nudge_hud(int(msg.get("dx", 0) or 0), int(msg.get("dy", 0) or 0))

        elif t == "RESET_HUD_POS":
            hud.reset_hud_position()

        elif t == "EXIT":
            os._exit(0)

    # cfg.ws_url: 기본 ws://127.0.0.1:8080/ws/agent -> /ws/hud로 치환
    base_ws = cfg["ws_url"] if isinstance(cfg, dict) else getattr(cfg, "ws_url", "ws://127.0.0.1:8080/ws/agent")
    hud_ws_url = str(base_ws).replace("/ws/agent", "/ws/hud")

    no_ws = cfg.get("no_ws", False) if isinstance(cfg, dict) else getattr(cfg, "no_ws", False)
    hud_ws = WSClient(hud_ws_url, _on_hud_cmd, enabled=(not no_ws) and (not no_hud))
    hud_ws.start()


    # OS 커서 숨기기(원할 때만)
    HIDE_OS_CURSOR = True  # 필요하면 False로 끄기

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
