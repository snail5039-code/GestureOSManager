import cv2
import mediapipe as mp
import threading
import time
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
# 통신 안정성을 위해 송신 버퍼 제한 및 타임아웃 설정
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=10)

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
pose = mp_pose.Pose(model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5)

def run_vision():
    cap = None
    for i in range(0, 3):
        temp_cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if temp_cap.isOpened():
            cap = temp_cap
            break
        temp_cap.release()

    if cap is None: return

    last_send_time = 0
    
    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success: continue

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(rgb)

            head_x, guard_value, attack_dir = 0.0, 0.0, "none"

            if results.pose_landmarks:
                landmarks = results.pose_landmarks.landmark
                nose = landmarks[mp_pose.PoseLandmark.NOSE]
                l_wrist = landmarks[mp_pose.PoseLandmark.LEFT_WRIST]
                r_wrist = landmarks[mp_pose.PoseLandmark.RIGHT_WRIST]
                l_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
                r_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]

                head_x = nose.x - 0.5
                
                # ✅ [핵심] 어퍼컷 판정 기준 상향 (코보다 위로 20% 지점)
                # 손이 이마 위로 확실히 올라가야 어퍼컷으로 인정
                if l_wrist.y < nose.y - 0.20 or r_wrist.y < nose.y - 0.20:
                    attack_dir = "uppercut"
                # ✅ 잽/스트레이트 판정 (어깨 너비 기준)
                elif l_wrist.x < l_shoulder.x - 0.10:
                    attack_dir = "jab"
                elif r_wrist.x > r_shoulder.x + 0.10:
                    attack_dir = "straight"
                
                # ✅ 가드 판정: 공격이 아닐 때만 + 손이 입 높이보다 위일 때만
                # 범위를 좁혀서(nose.y - 0.05) 어퍼컷 하러 올라가는 손과 겹치지 않게 함
                if attack_dir == "none":
                    if (l_wrist.y < nose.y + 0.05) or (r_wrist.y < nose.y + 0.05):
                        guard_value = 1.0

                # 모니터링 출력
                status_text = f"CMD: {attack_dir.upper()}"
                cv2.putText(frame, status_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255) if attack_dir != "none" else (0, 255, 0), 2)

            # ✅ 전송 주기 0.05초로 고정 (데이터 꼬임 방지)
            if time.time() - last_send_time > 0.05:
                socketio.emit('motion', {
                    'x': round(head_x, 3), 
                    'z': round(guard_value, 3) if attack_dir == "none" else 0.0, 
                    'dir': attack_dir
                })
                last_send_time = time.time()

            cv2.imshow('Boxing Game Monitor', frame)
            if cv2.waitKey(1) & 0xFF == 27: break
    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    threading.Thread(target=run_vision, daemon=True).start()
    socketio.run(app, host='127.0.0.1', port=65432, debug=False)