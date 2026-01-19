# py/gestureos_agent/modes/vkey.py
import multiprocessing as mp

# ---- try import Qt process entry (패키지/루트 둘 다 지원) ----
run_vkey_process = None
_import_errs = []
try:
    from gestureos_agent.qt_vkey_overlay import run_vkey_process as _rvp
    run_vkey_process = _rvp
except Exception as e1:
    _import_errs.append(repr(e1))
    try:
        from qt_vkey_overlay import run_vkey_process as _rvp2
        run_vkey_process = _rvp2
    except Exception as e2:
        _import_errs.append(repr(e2))


class VKeyHandler:
    """Virtual keyboard overlay bridge.

    - Toggle overlay with V_SIGN
    - Stream pointer + pinch state to Qt overlay process
    """

    def __init__(self):
        self._qt_ok = False
        self._qt_proc = None
        self._qt_cmd_q = None
        self._qt_evt_q = None

        self._overlay_visible = False
        self._enable_input = False

        self._last_gesture = "NONE"
        self._last_pinch = False
        self._last_send_ts = 0.0

        self.tap_seq = 0

    # ---------------------------------------------------------------------
    # OSK (optional)
    # ---------------------------------------------------------------------
    def open_windows_osk(self):
        # 기본은 no-op
        return

    # ---------------------------------------------------------------------
    # Qt process management
    # ---------------------------------------------------------------------
    def _qt_start(self) -> bool:
        if run_vkey_process is None:
            print("[VKEY] qt overlay import failed:", _import_errs, flush=True)
            self._qt_ok = False
            return False

        if self._qt_proc is not None and self._qt_proc.is_alive():
            self._qt_ok = True
            return True

        try:
            # Windows에서 mp + Qt는 spawn 권장
            try:
                mp.set_start_method("spawn", force=False)
            except Exception:
                pass

            self._qt_cmd_q = mp.Queue()
            self._qt_evt_q = mp.Queue()
            self._qt_proc = mp.Process(
                target=run_vkey_process,
                args=(self._qt_cmd_q, self._qt_evt_q),
                daemon=True,
            )
            self._qt_proc.start()
            self._qt_ok = True
            print("[VKEY] qt proc started pid=", self._qt_proc.pid, flush=True)
            return True
        except Exception as e:
            print("[VKEY] qt start failed:", repr(e), flush=True)
            self._qt_ok = False
            self._qt_proc = None
            self._qt_cmd_q = None
            self._qt_evt_q = None
            return False

    def _qt_send(self, msg: dict):
        q = self._qt_cmd_q
        if q is None:
            return
        try:
            q.put_nowait(msg)
        except Exception:
            try:
                q.put(msg)
            except Exception:
                pass

    def _qt_stop(self):
        try:
            self._qt_send({"type": "ACTIVE", "value": False})
            self._qt_send({"type": "ENABLE_INPUT", "value": False})
            self._qt_send({"type": "QUIT"})
        except Exception:
            pass

        p = self._qt_proc
        if p is not None:
            try:
                p.join(timeout=0.6)
            except Exception:
                pass
            try:
                if p.is_alive():
                    p.terminate()
            except Exception:
                pass

        self._qt_proc = None
        self._qt_cmd_q = None
        self._qt_evt_q = None
        self._qt_ok = False

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def reset(self):
        self._overlay_visible = False
        self._enable_input = False
        self._last_gesture = "NONE"
        self._last_pinch = False
        self._last_send_ts = 0.0
        self.tap_seq = 0
        self._qt_stop()

    def on_enter(self, auto_show: bool = True):
        self._qt_start()
        if auto_show:
            self._overlay_visible = True
            self._qt_send({"type": "ACTIVE", "value": True})

    def update(self, t: float, can_click: bool, cursor_lm, cursor_gesture: str):
        if not self._qt_start():
            return

        # 오버레이 토글: V_SIGN
        if cursor_gesture == "V_SIGN" and self._last_gesture != "V_SIGN":
            self._overlay_visible = not self._overlay_visible

        self._last_gesture = cursor_gesture

        # 입력 가능 여부
        self._enable_input = bool(can_click)

        # 포인터: index tip lm[8] normalized
        pointer01 = None
        if cursor_lm is not None and isinstance(cursor_lm, (list, tuple)) and len(cursor_lm) > 8:
            try:
                pointer01 = (float(cursor_lm[8][0]), float(cursor_lm[8][1]))
            except Exception:
                pointer01 = None

        # pinch: PINCH_INDEX
        pinch = (cursor_gesture == "PINCH_INDEX")

        # 60Hz 송신
        if (t - self._last_send_ts) >= (1.0 / 60.0):
            self._qt_send({"type": "ACTIVE", "value": bool(self._overlay_visible)})
            self._qt_send({"type": "ENABLE_INPUT", "value": bool(self._enable_input)})
            if pointer01 is not None:
                self._qt_send({"type": "POINTER", "value": [pointer01[0], pointer01[1]]})
            self._qt_send({"type": "PINCH", "value": bool(pinch)})
            self._last_send_ts = t

        # tap_seq (호환용)
        if pinch and not self._last_pinch:
            self.tap_seq += 1
        self._last_pinch = pinch


__all__ = ["VKeyHandler"]
