# py/main.py
import os
import sys
import time
import ctypes
import multiprocessing as mp
from dataclasses import replace

import subprocess
import socket
import signal
import atexit
import threading


def _set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class CfgProxy:
    def __init__(self, base, hud):
        self._base = base
        self.hud = hud

    def __getattr__(self, name):
        return getattr(self._base, name)


def _tcp_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _udp_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((host, port))
        return False
    except Exception:
        return True
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass


class PhoneAutoRunner:
    def __init__(self, py_root, enable=True, mjpeg_port=8081, udp_port=39500):
        self.py_root = py_root
        self.enable = bool(enable)
        self.mjpeg_port = int(mjpeg_port)
        self.udp_port = int(udp_port)
        self._started = False

    def start(self):
        if self._started:
            return
        self._started = True

        if not self.enable:
            print("[PHONE] disabled (--no-phone)", flush=True)
            return

        # MJPEG (http://0.0.0.0:8081/mjpeg)
        if _tcp_port_open("127.0.0.1", self.mjpeg_port):
            print(f"[PHONE] MJPEG already running on 127.0.0.1:{self.mjpeg_port} (skip)", flush=True)
        else:
            t = threading.Thread(target=self._run_mjpeg, daemon=True)
            t.start()
            print(f"[PHONE] MJPEG thread started (port={self.mjpeg_port})", flush=True)

        # UDP bridge (39500)
        if _udp_port_in_use(self.udp_port, "0.0.0.0"):
            print(f"[PHONE] UDP port {self.udp_port} already in use (skip xr_bridge)", flush=True)
        else:
            t = threading.Thread(target=self._run_xr_bridge, daemon=True)
            t.start()
            print(f"[PHONE] xr_bridge thread started (udp={self.udp_port})", flush=True)

    def _run_mjpeg(self):
        try:
            from phone import pc_stream_mjpeg as m
            # Flask reloader OFF (중복 프로세스 방지)
            m.app.run(host="0.0.0.0", port=int(self.mjpeg_port), threaded=True, use_reloader=False)
        except Exception as e:
            print("[PHONE] MJPEG thread error:", repr(e), flush=True)

    def _run_xr_bridge(self):
        try:
            from phone import xr_bridge as xb
            try:
                xb.UDP_PORT = int(self.udp_port)
            except Exception:
                pass
            xb.main()
        except Exception as e:
            print("[PHONE] xr_bridge thread error:", repr(e), flush=True)

    def stop(self):
        # in-proc thread workers stop when parent exits
        return


def main():
    _set_dpi_awareness()

    from gestureos_agent.config import parse_cli
    from gestureos_agent.hud_overlay import OverlayHUD
    import gestureos_agent.hud_overlay as ho
    from gestureos_agent.cursor_system import apply_invisible_cursor, restore_system_cursors
    from gestureos_agent.agents.hands_agent import HandsAgent
    from gestureos_agent.ws_client import WSClient

    print("[HUD] hud_overlay file =", ho.__file__, flush=True)

    agent_kind, cfg = parse_cli()

    if agent_kind == "color":
        cfg = replace(cfg, start_rush=True, rush_input="COLOR")

    no_hud = ("--no-hud" in sys.argv)

    no_phone = ("--no-phone" in sys.argv)
    runner = PhoneAutoRunner(py_root=os.path.dirname(os.path.abspath(__file__)), enable=(not no_phone))
    runner.start()

    hud = OverlayHUD(enable=(not no_hud))
    if not no_hud:
        hud.start()

    try:
        _no_ws = cfg.get("no_ws", False) if isinstance(cfg, dict) else getattr(cfg, "no_ws", False)
    except Exception:
        _no_ws = False

    hud_ws = None
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

    HIDE_OS_CURSOR = False
    if HIDE_OS_CURSOR and (not no_hud):
        try:
            cur_path = os.path.join(os.path.dirname(__file__), "gestureos_agent", "assets", "reticle", "invisible.cur")
            apply_invisible_cursor(cur_path)
        except Exception as e:
            print("[CURSOR] hide failed:", e, flush=True)

    try:
        cfg_for_agent = CfgProxy(cfg, hud)
        HandsAgent(cfg_for_agent).run()
    finally:
        try:
            runner.stop()
        except Exception:
            pass

        if HIDE_OS_CURSOR and (not no_hud):
            try:
                restore_system_cursors()
            except Exception:
                pass
        try:
            hud.stop()
        except Exception:
            pass


if __name__ == "__main__":
    mp.freeze_support()
    try:
        mp.set_start_method("spawn", force=True)
    except Exception:
        pass
    main()
