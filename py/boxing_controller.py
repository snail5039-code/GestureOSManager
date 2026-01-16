import cv2
import mediapipe as mp
import threading
import time
from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# MediaPipe Pose 설정
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
# ✅ model_complexity를 1로 높여 정확도를 우선시함
# ✅ min_detection_confidence를 0.5로 설정해 확실한 경우만 점을 찍게 함
pose = mp_pose.Pose(
    model_complexity=1, 
    min_detection_confidence=0.5, 
    min_tracking_confidence=0.5
)

def run_vision():
    cap = cv2.VideoCapture(0)
    
    while cap.isOpened():
        success, frame = cap.read()
        if not success: break

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)

        guard_value = 0.0
        head_x = 0.0

        if results.pose_landmarks:
            # ✅ 모든 관절 점과 연결선을 화면에 그립니다.
            mp_drawing.draw_landmarks(
                frame, 
                results.pose_landmarks, 
                mp_pose.POSE_CONNECTIONS,
                mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=3), # 점: 초록
                mp_drawing.DrawingSpec(color=(0, 0, 255), thickness=2) # 선: 빨강
            )
            
            # 특정 관절(코, 양 손목) 데이터 추출
            landmarks = results.pose_landmarks.landmark
            nose = landmarks[mp_pose.PoseLandmark.NOSE]
            l_wrist = landmarks[mp_pose.PoseLandmark.LEFT_WRIST]
            r_wrist = landmarks[mp_pose.PoseLandmark.RIGHT_WRIST]

            head_x = nose.x - 0.5
            # 가드 판정: 손목이 코보다 높을 때
            if l_wrist.y < nose.y or r_wrist.y < nose.y:
                guard_value = 1.0

            # ✅ 화면에 텍스트로 현재 좌표 출력 (디버깅용)
            cv2.putText(frame, f"Nose Y: {nose.y:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"L_Wrist Y: {l_wrist.y:.2f}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"R_Wrist Y: {r_wrist.y:.2f}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        # 데이터 전송
        socketio.emit('motion', {'x': round(head_x, 3), 'z': round(guard_value, 3)})

        cv2.imshow('Joint Tracking Monitor', frame)
        if cv2.waitKey(1) & 0xFF == 27: break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    threading.Thread(target=run_vision, daemon=True).start()
    socketio.run(app, host='127.0.0.1', port=65432, debug=False)