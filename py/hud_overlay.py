import sys
import time
import json
import argparse
import threading
from dataclasses import dataclass

import requests  # 서버에 데이터를 물어보는 도구 (HTTP용)
from websocket import WebSocketApp  # 서버의 실시간 방송을 듣는 도구 (웹소켓용)

# PySide6: 화면을 만들기 위한 핵심 도구들
from PySide6.QtCore import Qt, QRectF, QTimer, Signal, Slot
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

# 스프링 서버의 실시간 명령 통로 주소
WS_HUD_URL = "ws://127.0.0.1:8080/ws/hud"

# ------------------------------------------------------------
# 윈도우 전용: 창이 마우스 클릭을 방해하지 않게 설정
# ------------------------------------------------------------
def _win_click_through(hwnd: int):
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000     # 투명 층 사용
        WS_EX_TRANSPARENT = 0x00000020 # 마우스 클릭 통과
        WS_EX_TOOLWINDOW = 0x00000080  # 작업표시줄에서 숨김

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # 현재 창 스타일을 가져와서 '투명+통과+숨김' 스타일을 추가로 입힘
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
    except Exception as e:
        print("[HUD] Windows 설정 실패:", e)

# ------------------------------------------------------------
# 데이터 상자: 서버에서 받은 정보를 파이썬에서 쓰기 좋게 정리
# ------------------------------------------------------------
@dataclass
class AgentStatus:
    enabled: bool = False
    locked: bool = True
    mode: str = "MOUSE"
    gesture: str = "NONE"
    fps: float = 0.0
    canMove: bool = False
    canClick: bool = False
    scrollActive: bool = False
    ok: bool = False # 서버 통신 성공 여부

    @staticmethod
    def from_json(d: dict):
        """서버 JSON 데이터를 파이썬 객체로 변환"""
        return AgentStatus(
            enabled=bool(d.get("enabled", False)),
            locked=bool(d.get("locked", True)),
            mode=str(d.get("mode", "MOUSE")).upper(),
            gesture=str(d.get("gesture", d.get("lastGesture", "NONE"))),
            fps=float(d.get("fps", d.get("agentFps", 0.0)) or 0.0),
            canMove=bool(d.get("canMove", False)),
            canClick=bool(d.get("canClick", False)),
            scrollActive=bool(d.get("scrollActive", False)),
            ok=True,
        )

# ------------------------------------------------------------
# 메인 HUD 창 (Widget)
# ------------------------------------------------------------
class HudOverlay(QWidget):
    # ✅ Signal(신호): 다른 스레드에서 메인 스레드에 업무를 요청하는 '벨'
    sig_set_visible = Signal(bool)     # "화면 켜라/꺼라" 신호
    sig_exit = Signal()                # "프로그램 종료해라" 신호
    sig_apply_status = Signal(object)  # "데이터 새로고침해라" 신호
    sig_repaint = Signal()             # "화면 다시 그려라" 신호

    def __init__(self, poll_ms: int, status_url: str, position: str):
        super().__init__()
        self.poll_ms = poll_ms
        self.status_url = status_url
        self.position = position
        self.s = AgentStatus()
        self._last_ok_ts = 0.0 # 마지막 통신 시간 체크용

        # 창 스타일: 테두리 없음 | 항상 위 | 도구창 모드
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True) # 배경 투명
        self.setAttribute(Qt.WA_ShowWithoutActivating, True) # 포커스 뺏기 금지
        self.resize(360, 210)
        self._apply_position() # 위치 잡기

        # ✅ Signal과 Slot(실제 실행될 함수)을 연결함
        # Qt.QueuedConnection: 신호를 보낸 쪽과 받는 쪽이 달라도 안전하게 전달함
        self.sig_set_visible.connect(self._on_set_visible, Qt.QueuedConnection)
        self.sig_exit.connect(self._on_exit, Qt.QueuedConnection)
        self.sig_apply_status.connect(self._on_apply_status, Qt.QueuedConnection)
        self.sig_repaint.connect(self.update, Qt.QueuedConnection)

        # 0.1초 후 클릭 통과 기능 활성화
        QTimer.singleShot(100, self._enable_click_through)

        # 주기적으로 서버에 데이터를 물어볼 타이머 시작
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_async)
        self._timer.start(self.poll_ms)
        QTimer.singleShot(10, self._poll_async)

        # 웹소켓(실시간 명령) 전담 스레드 시작
        threading.Thread(target=self._ws_loop, daemon=True).start()

    def _apply_position(self):
        """화면 구석 여백 계산해서 이동"""
        screen = QApplication.primaryScreen().availableGeometry()
        margin = 18
        if self.position == "top-right":
            x, y = screen.right() - self.width() - margin, screen.top() + margin
        elif self.position == "top-left":
            x, y = screen.left() + margin, screen.top() + margin
        elif self.position == "bottom-right":
            x, y = screen.right() - self.width() - margin, screen.bottom() - self.height() - margin
        else:
            x, y = screen.left() + margin, screen.bottom() - self.height() - margin
        self.move(x, y)

    def _enable_click_through(self):
        """창의 고유 ID(hwnd)를 찾아 윈도우 설정 적용"""
        try:
            hwnd = int(self.winId())
            _win_click_through(hwnd)
        except Exception as e:
            print("[HUD] hwnd 실패:", e)

    # ----------------------------------------------------------
    # 데이터 수집 (HTTP Polling)
    # ----------------------------------------------------------
    def _poll_async(self):
        """메인 스레드가 멈추지 않게 별도 스레드에서 서버에 물어봄"""
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _poll_once(self):
        """실제 서버 통신 (백그라운드 스레드에서 실행됨)"""
        try:
            r = requests.get(self.status_url, timeout=1.2)
            r.raise_for_status()
            data = r.json()
            st = AgentStatus.from_json(data)
            # ✅ 성공하면 '데이터 적용해라'라고 메인 스레드에 신호 보냄
            self.sig_apply_status.emit(st)
        except Exception:
            self.s.ok = False
            # ✅ 실패하면 '빨간불 들어오게 화면 다시 그려라'라고 신호 보냄
            self.sig_repaint.emit()

    # ----------------------------------------------------------
    # 실시간 명령 수신 (WebSocket)
    # ----------------------------------------------------------
    def _ws_loop(self):
        """서버가 던지는 명령을 기다리는 무한 루프"""
        def on_open(ws): print("[HUD] WS connected:", WS_HUD_URL)
        def on_message(ws, msg: str):
            try:
                data = json.loads(msg)
                t = data.get("type")
                if t == "SET_VISIBLE":
                    enabled = bool(data.get("enabled", True))
                    # ✅ 직접 UI를 바꾸지 않고 신호를 보냄 (매우 안전)
                    self.sig_set_visible.emit(enabled)
                elif t == "EXIT":
                    self.sig_exit.emit()
            except Exception as e: print("[HUD] 에러:", e)

        def on_error(ws, err): print("[HUD] WS error:", err)
        def on_close(ws, code, reason): print("[HUD] WS closed:", code, reason)

        while True: # 연결 끊겨도 무한 재접속
            try:
                ws = WebSocketApp(WS_HUD_URL, on_open=on_open, on_message=on_message, 
                                  on_error=on_error, on_close=on_close)
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e: print("[HUD] ws_loop 예외:", e)
            time.sleep(1.0)

    # ----------------------------------------------------------
    # ✅ Slot(슬롯): 메인 스레드에서만 실행되는 UI 조작 함수들
    # ----------------------------------------------------------
    @Slot(bool)
    def _on_set_visible(self, enabled: bool):
        """신호를 받으면 실제로 창을 켜거나 끔"""
        if enabled: self.show()
        else: self.hide()

    @Slot()
    def _on_exit(self):
        """종료 신호를 받으면 프로그램 종료"""
        QApplication.quit()

    @Slot(object)
    def _on_apply_status(self, st):
        """데이터 신호를 받으면 정보를 저장하고 화면을 갱신"""
        self.s = st
        self._last_ok_ts = time.time()
        self.update() # paintEvent 실행 유도

    # ----------------------------------------------------------
    # 그리기 기능 (HUD 디자인)
    # ----------------------------------------------------------
    def _draw_round_panel(self, p: QPainter, rect: QRectF):
        """어두운 배경 판 그리기"""
        radius = 18.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, QColor(10, 15, 25, 180)) # 짙은 투명 남색
        p.setPen(QPen(QColor(110, 140, 255, 90), 1.6)) # 은은한 테두리
        p.drawPath(path)

    def _pill(self, p: QPainter, x, y, w, h, label, value, color: QColor):
        """알약 모양 배지 하나 그리기"""
        rect = QRectF(x, y, w, h)
        radius = h / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        bg = QColor(color.red(), color.green(), color.blue(), 45)
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 120), 1.2))
        p.drawPath(path)
        p.setPen(QColor(235, 245, 255, 220))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, f"{label}: {value}")

    def paintEvent(self, event):
        """화면을 실제로 그리는 작업 (새로고침될 때마다 호출됨)"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pad = 8.0
        panel = QRectF(pad, pad, self.width() - pad*2, self.height() - pad*2)

        self._draw_round_panel(p, panel) # 배경

        # 제목
        p.setPen(QColor(240, 248, 255, 230))
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.drawText(panel.adjusted(14, 10, -14, -10), Qt.AlignLeft | Qt.AlignTop, "GestureOS HUD")

        # 서버 연결 상태 표시 (2초 응답 없으면 DOWN)
        ok = self.s.ok and (time.time() - self._last_ok_ts) < 2.0
        self._pill(p, panel.right() - 120, panel.top() + 10, 104, 26, "HTTP", "OK" if ok else "DOWN", 
                   QColor(60, 220, 140) if ok else QColor(255, 90, 90))

        # 데이터 배지들 배치 (가로, 세로 위치 잡기)
        x0, y0, gap, pw, ph = panel.left() + 14, panel.top() + 46, 10, 158, 28
        self._pill(p, x0, y0, pw, ph, "Enabled", "ON" if self.s.enabled else "OFF", QColor(60, 220, 140) if self.s.enabled else QColor(255, 90, 90))
        self._pill(p, x0 + pw + gap, y0, pw, ph, "Locked", "ON" if self.s.locked else "OFF", QColor(255, 200, 80) if self.s.locked else QColor(60, 220, 140))
        y1 = y0 + ph + gap
        self._pill(p, x0, y1, pw, ph, "Mode", self.s.mode, QColor(90, 160, 255))
        self._pill(p, x0 + pw + gap, y1, pw, ph, "Gesture", self.s.gesture, QColor(170, 110, 255))
        y2 = y1 + ph + gap
        self._pill(p, x0, y2, pw, ph, "FPS", f"{self.s.fps:.1f}", QColor(120, 230, 255))
        self._pill(p, x0 + pw + gap, y2, pw, ph, "Move", "YES" if self.s.canMove else "NO", QColor(60, 220, 140) if self.s.canMove else QColor(150, 160, 170))
        y3 = y2 + ph + gap
        self._pill(p, x0, y3, pw, ph, "Click", "YES" if self.s.canClick else "NO", QColor(60, 220, 140) if self.s.canClick else QColor(150, 160, 170))
        self._pill(p, x0 + pw + gap, y3, pw, ph, "Scroll", "ON" if self.s.scrollActive else "OFF", QColor(60, 220, 140) if self.s.scrollActive else QColor(150, 160, 170))

# ------------------------------------------------------------
# 프로그램 시작점
# ------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status-url", default="http://127.0.0.1:8080/api/control/status")
    ap.add_argument("--poll-ms", type=int, default=200)
    ap.add_argument("--pos", default="top-right", choices=["top-right", "top-left", "bottom-right", "bottom-left"])
    args = ap.parse_args()

    app = QApplication(sys.argv)
    w = HudOverlay(poll_ms=args.poll_ms, status_url=args.status_url, position=args.pos)
    w.show()
    sys.exit(app.exec()) # 메인 이벤트 루프 시작

if __name__ == "__main__":
    main()