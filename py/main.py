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
    def __init__(self, py_root: str, enable: bool = True, mjpeg_port: int = 8081, udp_port: int = 39500):
        self.py_root = py_root
        self.enable = enable
        self.mjpeg_port = mjpeg_port
        self.udp_port = udp_port
        self.procs = []

        temp = os.getenv("TEMP") or os.getenv("TMP") or "."
        self.log_dir = os.path.join(temp, "GestureOS_phone")
        os.makedirs(self.log_dir, exist_ok=True)

    def start(self):
        if not self.enable:
            print("[PHONE] 폰 연동 꺼짐 (기본값). 필요하면 --phone 으로 실행하세요.", flush=True)
            return

        # 켜는 순간 이 PC의 화면과 입력이 같은 네트워크에 열린다.
        # 아직 인증이 없으므로, 무엇이 열리는지 반드시 눈에 보이게 알린다.
        print("", flush=True)
        print("[PHONE] ============================================================", flush=True)
        print("[PHONE]  폰 연동을 켭니다. 이 PC가 같은 네트워크에 아래를 공개합니다.", flush=True)
        print(f"[PHONE]   - TCP {self.mjpeg_port} : 화면 전체 실시간 스트리밍 (인증 없음)", flush=True)
        print(f"[PHONE]   - UDP {self.udp_port} : 마우스/키보드 원격 입력 (인증 없음)", flush=True)
        print("[PHONE]  신뢰할 수 없는 공용 Wi-Fi에서는 켜지 마세요.", flush=True)
        print("[PHONE] ============================================================", flush=True)
        print("", flush=True)

        phone_dir = os.path.join(self.py_root, "phone")
        pc_stream = os.path.join(phone_dir, "pc_stream_mjpeg.py")
        xr_bridge = os.path.join(phone_dir, "xr_bridge.py")

        if _tcp_port_open("127.0.0.1", self.mjpeg_port):
            print(f"[PHONE] MJPEG already running on 127.0.0.1:{self.mjpeg_port} (skip)", flush=True)
        else:
            self._spawn("pc_stream_mjpeg", pc_stream)

        if _udp_port_in_use(self.udp_port, "0.0.0.0"):
            print(f"[PHONE] UDP port {self.udp_port} already in use (skip xr_bridge)", flush=True)
        else:
            self._spawn("xr_bridge", xr_bridge)

        atexit.register(self.stop)

    def _spawn(self, name: str, script_path: str):
        if not os.path.exists(script_path):
            print(f"[PHONE] missing script: {script_path} (skip {name})", flush=True)
            return

        log_path = os.path.join(self.log_dir, f"{name}.log")
        try:
            log_fp = open(log_path, "a", encoding="utf-8")
        except Exception:
            log_fp = None

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        cmd = [sys.executable, script_path]
        try:
            p = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(script_path),
                creationflags=creationflags,
                stdout=log_fp if log_fp else subprocess.DEVNULL,
                stderr=log_fp if log_fp else subprocess.DEVNULL,
            )
            self.procs.append((name, p, log_fp))
            print(f"[PHONE] started {name} (pid={p.pid}) log={log_path}", flush=True)
        except Exception as e:
            print(f"[PHONE] failed to start {name}: {e}", flush=True)
            try:
                if log_fp:
                    log_fp.close()
            except Exception:
                pass

    def stop(self):
        if not self.procs:
            return

        for name, p, log_fp in self.procs:
            try:
                if p.poll() is not None:
                    continue

                if os.name == "nt":
                    try:
                        p.send_signal(signal.CTRL_BREAK_EVENT)
                        p.wait(timeout=1.5)
                    except Exception:
                        pass

                if p.poll() is None:
                    try:
                        p.terminate()
                        p.wait(timeout=1.0)
                    except Exception:
                        pass

                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass

                print(f"[PHONE] stopped {name}", flush=True)
            except Exception:
                pass
            finally:
                try:
                    if log_fp:
                        log_fp.flush()
                        log_fp.close()
                except Exception:
                    pass

        self.procs.clear()


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

    # 폰 연동(화면 스트리밍 + 원격 입력)은 기본 OFF.
    # 인증이 없는 상태로 네트워크에 노출되므로, 쓰겠다고 명시할 때만 띄운다.
    # --no-phone 은 예전 실행 스크립트 호환을 위해 계속 받아준다(항상 OFF).
    phone_enabled = ("--phone" in sys.argv) and ("--no-phone" not in sys.argv)
    runner = PhoneAutoRunner(py_root=os.path.dirname(os.path.abspath(__file__)), enable=phone_enabled)
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
