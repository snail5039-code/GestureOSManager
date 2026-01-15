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


def main():
    agent_kind, cfg = parse_cli()

    # Backward-compat: --agent=color -> start RUSH_COLOR
    if agent_kind == "color":
        cfg = replace(cfg, start_rush=True, rush_input="COLOR")

    no_hud = ("--no-hud" in sys.argv)

    hud = OverlayHUD(enable=(not no_hud))
    hud.start()

    # ✅ Listen HUD show/hide commands from Spring WS (/ws/hud)
    #    Front: POST /api/hud/show?enabled=true|false  -> Server broadcasts to /ws/hud
    #    This client receives {"type":"SET_VISIBLE","enabled":true|false} and toggles the overlay panel.
    try:
        _no_ws = cfg.get("no_ws", False) if isinstance(cfg, dict) else getattr(cfg, "no_ws", False)
    except Exception:
        _no_ws = False

    if (not _no_ws) and (not no_hud):
        try:
            agent_url = getattr(cfg, "ws_url", "ws://127.0.0.1:8080/ws/agent")
            hud_url = agent_url.replace("/ws/agent", "/ws/hud") if "/ws/agent" in agent_url else agent_url.rstrip("/") + "/ws/hud"

            def _on_hud_cmd(data: dict):
                try:
                    typ = str(data.get("type", "")).upper()
                    if typ == "SET_VISIBLE":
                        v = data.get("enabled", data.get("visible", True))
                        hud.set_visible(bool(v))
                    elif typ == "EXIT":
                        hud.stop()
                        os._exit(0)
                except Exception as e:
                    print("[HUD_WS] on_command error:", e, flush=True)

            hud_ws = WSClient(hud_url, _on_hud_cmd, enabled=True)
            hud_ws.start()
            print("[HUD_WS] connecting:", hud_url, flush=True)
        except Exception as e:
            print("[HUD_WS] start failed:", e, flush=True)

    # OS 커서 숨기기(원할 때만)
    HIDE_OS_CURSOR = True
    if HIDE_OS_CURSOR and (not no_hud):
        try:
            cur_path = os.path.join(os.path.dirname(__file__), "gestureos_agent", "assets", "reticle", "invisible.cur")
            apply_invisible_cursor(cur_path)
        except Exception as e:
            print("[CURSOR] hide failed:", e, flush=True)

    try:
        # frozen cfg에 hud를 붙여서 전달
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
