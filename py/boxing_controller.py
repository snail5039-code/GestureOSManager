import cv2
import mediapipe as mp
import threading
import time
import math
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(model_complexity=1, min_detection_confidence=0.8, min_tracking_confidence=0.8)

# 공격/가드 상태 관리
box_state = {
    "active": False,
    "hand": None,
    "path_x": [], "path_y": [], "path_z": [],
    "start_x": 0, "start_y": 0, "start_z": 0,
    "start_time": 0,
    "max_dx": 0, "max_dy": 0, "max_dz": 0,
    "min_y": 0.0,
}
chance_active = False

# ===============================
# AntiGravity용 Jab 판정 최적화 (User Provided)
# ===============================

# 설정값
SAMPLE_INTERVAL = 0.12   # 샘플링 간격 (0.1~0.15초)
WINDOW_SIZE = 5          # 최근 프레임 수
THRESHOLD_X = 0.015      # X 이동 기준값 (Modified: 15 -> 0.015 for normalized coords)
MIN_CONSECUTIVE = 3      # 연속 프레임 기준
MAX_DELAY = 1.0          # 판정 후 최대 지연 시간 (초)

# 버퍼 초기화
x_moves = []
consecutive_frames_x_move = 0
jab_detected = False
last_jab_time = 0
last_jab_valid_ts = 0    # Trigger timestamp storage

def update_jab(current_x_move, current_time):
    global x_moves, consecutive_frames_x_move, jab_detected, last_jab_time

    # 1️⃣ 스무딩
    x_moves.append(current_x_move)
    if len(x_moves) > WINDOW_SIZE:
        x_moves.pop(0)
    smoothed_x_move = sum(x_moves) / len(x_moves)

    # 2️⃣ 최소 유지 시간
    if smoothed_x_move > THRESHOLD_X:
        consecutive_frames_x_move += 1
    else:
        consecutive_frames_x_move = 0

    # 3️⃣ 판정
    if consecutive_frames_x_move >= MIN_CONSECUTIVE:
        # 3초 이내 판정 제한
        if current_time - last_jab_time > MAX_DELAY:
            jab_detected = True
            last_jab_time = current_time
        else:
            jab_detected = False
    else:
        jab_detected = False

    return jab_detected

chance_requested = False
force_attack_mode = False
chance_phase = "idle"  # "idle" | "ready" | "analyzing"
chance_consumed = False
prev_hand = {
    "left": {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0, "init": False},
    "right": {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0, "init": False},
}
prev_shoulder = {
    "left": {"z": 0.0, "init": False},
    "right": {"z": 0.0, "init": False},
}

def elbow_angle(shoulder, elbow, wrist):
    ax, ay = shoulder.x - elbow.x, shoulder.y - elbow.y
    bx, by = wrist.x - elbow.x, wrist.y - elbow.y
    dot = ax * bx + ay * by
    mag_a = (ax * ax + ay * ay) ** 0.5
    mag_b = (bx * bx + by * by) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    cos_v = max(-1.0, min(1.0, dot / (mag_a * mag_b)))
    return (math.degrees(math.acos(cos_v)))

@socketio.on("chance")
def handle_chance(data):
    global chance_active, chance_requested, chance_phase, box_state, chance_consumed
    if force_attack_mode:
        chance_requested = True
        chance_active = True
        chance_phase = "ready"
        chance_consumed = False
        return
    chance_requested = bool(data.get("active"))
    chance_active = chance_requested
    if chance_requested:
        chance_phase = "ready"
        chance_consumed = False
    else:
        chance_phase = "idle"
        chance_consumed = False
        box_state["active"] = False
        box_state["path_x"] = []
        box_state["path_y"] = []
        box_state["path_z"] = []

def run_vision():
    global box_state, chance_active, chance_requested, prev_hand, prev_shoulder, last_jab_valid_ts, chance_phase, chance_consumed
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    last_send_time = 0
    last_defense = "none"
    last_defense_time = 0.0
    defense_hold = 0.15
    min_punch_time = 0.18
    max_punch_time = 0.45
    speed_threshold = 0.008
    speed_end = 0.004
    extended_angle = 150
    bent_angle = 120
    z_threshold = 0.04
    y_threshold = 0.08
    x_small = 0.04
    x_large = 0.1
    shoulder_rot_threshold = 0.01
    uppercut_elbow_max = 165

    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            continue
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)

        head_x, guard_val, final_attack = 0.0, 0.0, "none"

        if results.pose_landmarks:
            lm = results.pose_landmarks.landmark
            nose = lm[mp_pose.PoseLandmark.NOSE]
            lw, rw = lm[mp_pose.PoseLandmark.LEFT_WRIST], lm[mp_pose.PoseLandmark.RIGHT_WRIST]
            le, re = lm[mp_pose.PoseLandmark.LEFT_ELBOW], lm[mp_pose.PoseLandmark.RIGHT_ELBOW]
            ls, rs = lm[mp_pose.PoseLandmark.LEFT_SHOULDER], lm[mp_pose.PoseLandmark.RIGHT_SHOULDER]

            head_x = nose.x - 0.5
            now_t = time.time()

            def hand_metrics(hand, elbow, shoulder, prev):
                if not prev["init"]:
                    return 0.0, 0.0, 0.0, 0.0, elbow_angle(shoulder, elbow, hand)
                dx = hand.x - prev["x"]
                dy = hand.y - prev["y"]
                dz = hand.z - prev["z"]
                speed = (dx * dx + dy * dy + dz * dz) ** 0.5
                angle = elbow_angle(shoulder, elbow, hand)
                return dx, dy, dz, speed, angle

            # 양손 메트릭 항상 계산 (찬스타이밍에서 어느 손이 공격할지 모르니까)
            l_dx, l_dy, l_dz, l_speed, l_angle = hand_metrics(lw, le, ls, prev_hand["left"])
            r_dx, r_dy, r_dz, r_speed, r_angle = hand_metrics(rw, re, rs, prev_hand["right"])

            if chance_requested:
                if l_speed != r_speed:
                    is_left = l_speed > r_speed
                else:
                    is_left = lw.z < rw.z
            else:
                is_left = lw.z < rw.z

            active_hand = lw if is_left else rw
            active_elbow = le if is_left else re
            active_shldr = ls if is_left else rs

            curr_x, curr_y, curr_z = active_hand.x, active_hand.y, active_hand.z
            dx = l_dx if is_left else r_dx
            dy = l_dy if is_left else r_dy
            dz = l_dz if is_left else r_dz
            speed = l_speed if is_left else r_speed
            elbow_ang = l_angle if is_left else r_angle

            # 가드 판정 (일반 모드에서만)
            if chance_requested:
                is_guarding = False
                guard_val = 0.0
            else:
                # 가드: 양손이 얼굴 근처 + 머리 중심 유지 (손 거리 기준 완화)
                left_guard = abs(lw.x - nose.x) < 0.25 and nose.y - 0.05 < lw.y < nose.y + 0.35
                right_guard = abs(rw.x - nose.x) < 0.25 and nose.y - 0.05 < rw.y < nose.y + 0.35
                is_guarding = left_guard and right_guard and abs(head_x) < 0.25
                guard_val = 1.0 if is_guarding else 0.0

            # Update Jab Optimization (Run every frame)
            # Use forward movement (-dz) as signal. Only count if moving forward.
            jab_signal = -dz if dz < 0 else 0
            if update_jab(jab_signal, now_t):
                last_jab_valid_ts = now_t


            # 공격 감지 (찬스타임일 때만, 이미 소비되지 않았을 때)
            if chance_requested and not is_guarding and not chance_consumed:
                if not box_state["active"]:
                    # 공격 시작 조건 강화: 움직임의 명확한 의도 필요
                    # 어퍼컷 시작: 수직 상향 이동이 지배적일 때만
                    uppercut_start = (
                        dy < -y_threshold * 0.6  # 상향 이동 필수
                        and abs(dx) < x_large * 0.5  # 수평 이동 최소
                        and abs(dz) < z_threshold * 0.5  # 깊이 이동 최소
                        and elbow_ang < uppercut_elbow_max
                    )
                    # 직선 시작: 깊이(z) 방향 움직임이 뚜렷할 때만
                    straight_start = (
                        dz < -z_threshold * 0.5  # 깊이 이동 필수
                        and elbow_ang > extended_angle
                    )
                    # 훅 시작: 수평(x) 지배적, 깊이(z) 최소
                    hook_start = (
                        abs(dx) > x_large * 0.6  # 수평 이동 지배적
                        and abs(dz) < z_threshold * 0.6  # 깊이 이동 최소
                        and abs(dy) < y_threshold * 0.8  # 수직 이동 제한
                    )
                    
                    # 속도 임계값을 완화하고 훅 시작 조건 포함
                    if speed > speed_threshold and (abs(dx) > 0.01 or dz < -0.01 or dy < -0.01):
                        box_state = {
                            "active": True,
                            "hand": "left" if is_left else "right",
                            "path_x": [curr_x],
                            "path_y": [curr_y],
                            "path_z": [curr_z],
                            "start_x": curr_x, "start_y": curr_y, "start_z": curr_z,
                            "start_time": now_t,
                            "max_dx": abs(dx), "max_dy": abs(dy), "max_dz": abs(dz),
                            "min_y": curr_y,
                        }
                        chance_phase = "analyzing"
                elif box_state["active"]:
                    if box_state["hand"] != ("left" if is_left else "right"):
                        active_hand = lw if box_state["hand"] == "left" else rw
                        active_elbow = le if box_state["hand"] == "left" else re
                        active_shldr = ls if box_state["hand"] == "left" else rs
                        curr_x, curr_y, curr_z = active_hand.x, active_hand.y, active_hand.z
                        if box_state["hand"] == "left":
                            dx, dy, dz, speed, elbow_ang = l_dx, l_dy, l_dz, l_speed, l_angle
                        else:
                            dx, dy, dz, speed, elbow_ang = r_dx, r_dy, r_dz, r_speed, r_angle

                    box_state["path_x"].append(curr_x)
                    box_state["path_y"].append(curr_y)
                    box_state["path_z"].append(curr_z)
                    box_state["max_dx"] = max(box_state["max_dx"], abs(dx))
                    box_state["max_dy"] = max(box_state["max_dy"], abs(dy))
                    box_state["max_dz"] = max(box_state["max_dz"], abs(dz))
                    box_state["min_y"] = min(box_state["min_y"], curr_y)

                    elapsed = now_t - box_state["start_time"]
                    # 감속 감지 또는 타임아웃 시 판정 (감속 임계값을 더 관대하게)
                    should_judge = (elapsed >= max_punch_time) or (elapsed >= min_punch_time and speed < speed_end * 1.5)
                    
                    if should_judge:
                        dx_total = curr_x - box_state["start_x"]
                        dy_total = curr_y - box_state["start_y"]
                        dz_total = curr_z - box_state["start_z"]
                        x_move = abs(dx_total)
                        y_move = abs(dy_total)
                        z_move = abs(dz_total)

                        other_shldr = rs if box_state["hand"] == "left" else ls
                        other_prev = prev_shoulder["right"] if box_state["hand"] == "left" else prev_shoulder["left"]
                        shoulder_rotation = other_prev["init"] and (other_shldr.z - other_prev["z"] > shoulder_rot_threshold)

                        uppercut_i_shape = curr_y < active_elbow.y and box_state["start_y"] > active_shldr.y
                        
                        # 판정 우선순위 (1순위부터 4순위까지, 오직 하나만 판정)
                        # 1️⃣ uppercut (Y축 지배 + 아래→위 동작)
                        uppercut_like = (
                            dy_total < 0
                            and y_move >= x_move * 1.5
                            and y_move >= z_move * 1.2
                            and x_move < x_large * 0.6
                            and elbow_ang < uppercut_elbow_max
                            and curr_y < active_elbow.y + 0.02
                        )
                        
                        # 2️⃣ hook (X축 지배 + Z/Y 최소) - 훅 보호막
                        hook_like = (
                            x_move > x_large
                            and x_move >= y_move * 1.6
                            and x_move >= z_move * 1.4
                            and y_move < y_threshold * 0.7
                            and abs(dy_total) < y_threshold * 0.4
                        )
                        
                        if uppercut_like:
                            final_attack = "uppercut"
                        elif hook_like:
                            final_attack = "hook"
                        # 3️⃣ straight / jab (Z축 지배, 훅·어퍼컷 아닐 때만)
                        elif not uppercut_like and not hook_like:
                            # 3-1️⃣ straight (Z축 지배 + X 제약)
                            if (
                                dz_total < -z_threshold
                                and z_move >= x_move * 1.2
                                and z_move >= y_move * 1.3
                                and dy_total >= -y_threshold * 0.5
                                and curr_y >= active_elbow.y - 0.02
                                and x_move >= x_small
                            ):
                                final_attack = "straight"
                            # 3-2️⃣ jab (Z축 짧고 빠른 직선, straight 아닐 때만)
                            elif (
                                dz_total < -z_threshold * 0.7
                                and z_move >= x_move * 1.1
                                and z_move >= y_move * 1.2
                                and dy_total >= -y_threshold * 0.3
                                and curr_y >= active_elbow.y - 0.02
                                and x_move < x_small * 0.8
                                and elapsed < 0.22
                            ):
                                final_attack = "jab"

                        box_state["active"] = False
                        if final_attack != "none":
                            chance_consumed = True
                            chance_active = False
                            chance_requested = False
                            chance_phase = "idle"

            # 일반 모드에서는 가드/위빙만 emit (공격 판정 프레임 제외)
            if not chance_requested and final_attack == "none":
                is_punch_like = speed > speed_threshold and elbow_ang > extended_angle
                if abs(head_x) > 0.18 and not is_punch_like:
                    now_t = time.time()
                    if last_defense != "weaving":
                        last_defense = "weaving"
                        last_defense_time = now_t
                    if now_t - last_defense_time >= defense_hold:
                        final_attack = "weaving"
                elif is_guarding and not is_punch_like:
                    now_t = time.time()
                    if last_defense != "guard":
                        last_defense = "guard"
                        last_defense_time = now_t
                    if now_t - last_defense_time >= defense_hold:
                        final_attack = "guard"
                else:
                    last_defense = "none"

            prev_hand["left"] = {"x": lw.x, "y": lw.y, "z": lw.z, "t": now_t, "init": True}
            prev_hand["right"] = {"x": rw.x, "y": rw.y, "z": rw.z, "t": now_t, "init": True}
            prev_shoulder["left"] = {"z": ls.z, "init": True}
            prev_shoulder["right"] = {"z": rs.z, "init": True}

        # 화면 디버깅
        if chance_phase == "analyzing":
            status_msg = "ANALYZING..."
        elif chance_phase == "ready":
            status_msg = "READY"
        else:
            status_msg = ""
        
        if status_msg:
            cv2.putText(frame, status_msg, (10, 40), 1, 1.5, (0, 255, 255), 2)
        
        # START 디버그 표시
        if box_state["active"]:
            cv2.putText(frame, "START", (10, 70), 1, 1.5, (0, 255, 0), 2)
        
        # 찬스타임 상태 디버그 (보너스)
        cv2.putText(
            frame,
            f"chance={chance_requested} active={box_state['active']} consumed={chance_consumed}",
            (10, 120),
            1, 1.1, (255, 0, 255), 2
        )
        
        if final_attack != "none":
            cv2.putText(frame, f"ACTION: {final_attack.upper()}", (10, 100), 1, 2.5, (0, 0, 255), 3)

        # Debug overlay
        if results.pose_landmarks:
            debug_y = 140
            elapsed_dbg = 0.0
            if box_state["active"]:
                elapsed_dbg = time.time() - box_state["start_time"]
            cv2.putText(frame, f"speed={speed:.3f}", (10, debug_y), 1, 1.4, (255, 255, 0), 2)
            debug_y += 22
            cv2.putText(frame, f"dx={dx:.3f} dy={dy:.3f} dz={dz:.3f}", (10, debug_y), 1, 1.2, (255, 255, 0), 2)
            debug_y += 22
            cv2.putText(frame, f"elbow={elbow_ang:.1f}", (10, debug_y), 1, 1.2, (255, 255, 0), 2)
            debug_y += 22
            cv2.putText(frame, f"active={box_state['active']} t={elapsed_dbg:.2f}", (10, debug_y), 1, 1.2, (255, 255, 0), 2)
            debug_y += 22
            cv2.putText(frame, f"START chk spd={speed:.3f} dx={dx:.3f} dy={dy:.3f} dz={dz:.3f}", (10, debug_y), 1, 1.0, (0, 200, 255), 2)

        cv2.imshow("Motion Debug", frame)
        if cv2.waitKey(1) & 0xFF == 27:  # ESC
            break

        # SocketIO emit
        if time.time() - last_send_time > 0.05:
            socketio.emit("motion", {"x": round(head_x,3), "z": round(guard_val,3), "dir": final_attack, "t": time.time()})
            last_send_time = time.time()

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    threading.Thread(target=run_vision, daemon=True).start()
    socketio.run(app, host="127.0.0.1", port=65432, debug=False)
