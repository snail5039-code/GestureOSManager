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
THRESHOLD_X = 0.015      # X 이동 기준값 (Normalized)
MIN_CONSECUTIVE = 3      # 연속 프레임 기준
MAX_DELAY = 1.0          # 판정 후 최대 지연 시간 (초)

MIN_HAND_MOVE = 0.06        # 손 최소 총 이동량
MIN_HAND_SPEED = 0.012     # 손 최소 순간 속도
MIN_FORWARD_SPEED = 0.012
MIN_FORWARD_DZ = 0.06

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

def reset_chance_fsm():
    global chance_active, chance_requested, chance_phase
    global chance_consumed, attack_attempted, intent_counter
    global box_state

    chance_active = False
    # chance_requested = False  <-- REMOVED to prevent FSM prison
    chance_phase = "idle"
    chance_consumed = False
    attack_attempted = False
    intent_counter = 0

    box_state = {
        "active": False,
        "hand": None,
        "path_x": [], "path_y": [], "path_z": [],
        "start_x": 0, "start_y": 0, "start_z": 0,
        "start_time": 0,
        "max_dx": 0, "max_dy": 0, "max_dz": 0,
        "min_y": 0.0,
    }

chance_requested = False
force_attack_mode = False
chance_phase = "idle"  # "idle" | "ready" | "analyzing"
chance_consumed = False
chance_start_time = 0.0
attack_attempted = False
intent_counter = 0
INTENT_SPEED = 0.012
INTENT_FRAMES = 3

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
    global chance_active, chance_requested, chance_phase, box_state, chance_consumed, chance_start_time, attack_attempted, intent_counter
    if force_attack_mode:
        chance_requested = True
        chance_active = True
        chance_phase = "ready"
        chance_consumed = False
        attack_attempted = False
        intent_counter = 0
        chance_start_time = time.time()
        return
    chance_requested = bool(data.get("active")) 
    chance_active = chance_requested
    if chance_requested:
        chance_phase = "ready"
        chance_consumed = False
        attack_attempted = False
        intent_counter = 0
        chance_start_time = time.time()
    else:
        chance_phase = "idle"
        chance_consumed = False
        box_state["active"] = False
        box_state["path_x"] = []
        box_state["path_y"] = []
        box_state["path_z"] = []

def run_vision():
    global box_state, chance_active, chance_requested, prev_hand, prev_shoulder, last_jab_valid_ts, chance_phase, chance_consumed, chance_start_time, attack_attempted, intent_counter
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    last_send_time = 0
    last_defense = "none"
    last_defense_time = 0.0
    defense_hold = 0.15
    min_punch_time = 0.12
    max_punch_time = 0.45
    speed_threshold = 0.005
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
        now_t = time.time()

        # FSM Auto-Recovery
        if chance_requested and chance_phase == "idle":
            chance_phase = "ready"

        if chance_requested and chance_phase == "ready" and not attack_attempted and not chance_consumed:
            if now_t - chance_start_time > 1.2:
                final_attack = "fail"
                reset_chance_fsm()

        if results.pose_landmarks:
            lm = results.pose_landmarks.landmark
            nose = lm[mp_pose.PoseLandmark.NOSE]
            lw, rw = lm[mp_pose.PoseLandmark.LEFT_WRIST], lm[mp_pose.PoseLandmark.RIGHT_WRIST]
            le, re = lm[mp_pose.PoseLandmark.LEFT_ELBOW], lm[mp_pose.PoseLandmark.RIGHT_ELBOW]
            ls, rs = lm[mp_pose.PoseLandmark.LEFT_SHOULDER], lm[mp_pose.PoseLandmark.RIGHT_SHOULDER]

            head_x = nose.x - 0.5

            def hand_metrics(hand, elbow, shoulder, prev):
                if not prev["init"]:
                    return 0.0, 0.0, 0.0, 0.0, elbow_angle(shoulder, elbow, hand)
                dx = hand.x - prev["x"]
                dy = hand.y - prev["y"]
                dz = hand.z - prev["z"]
                speed = (dx * dx + dy * dy + dz * dz) ** 0.5
                angle = elbow_angle(shoulder, elbow, hand)
                return dx, dy, dz, speed, angle

            # 양손 메트릭 항상 계산
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
                left_guard = abs(lw.x - nose.x) < 0.25 and nose.y - 0.05 < lw.y < nose.y + 0.35
                right_guard = abs(rw.x - nose.x) < 0.25 and nose.y - 0.05 < rw.y < nose.y + 0.35
                is_guarding = left_guard and right_guard and abs(head_x) < 0.25
                guard_val = 1.0 if is_guarding else 0.0

            # Update Jab Optimization
            jab_signal = -dz if dz < 0 else 0
            if update_jab(jab_signal, now_t):
                last_jab_valid_ts = now_t

            # 공격 감지 (찬스타임일 때만)
            if chance_requested and not is_guarding and not chance_consumed:
                # ❗ 위빙 중이면 공격 시작 금지
                if abs(head_x) > 0.18:
                    intent_counter = 0
                elif not box_state["active"]:
                    # Check body forward movement (weaving/leaning)
                    prev_z = prev_shoulder["left" if is_left else "right"]["z"]
                    body_forward = abs(active_shldr.z - prev_z) > 0.015

                    if body_forward:
                        intent_counter = 0
                    else:
                        # 손의 독립적 움직임만 공격 의도로 인정
                        hand_forward = dz < -0.02
                        hand_swing = abs(dx) > 0.025
                        hand_lift = dy < -0.025
                        hand_motion_energy = abs(dx) + abs(dy) + abs(dz)
                        
                        # Hand must be in front of shoulder (relative check)
                        hand_forward_relative = (curr_z - active_shldr.z) < -0.03

                        if (
                            (hand_forward or hand_swing or hand_lift)
                            and hand_motion_energy > 0.045   # 🔒 몸 이동 컷
                            and speed > INTENT_SPEED
                            and hand_forward_relative      # 🔒 Added relative check
                        ):
                            intent_counter += 1
                        else:
                            intent_counter = 0

                    if intent_counter >= INTENT_FRAMES:
                        attack_attempted = True
                        intent_counter = 0
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
                    dx_total = curr_x - box_state["start_x"]
                    dy_total = curr_y - box_state["start_y"]
                    dz_total = curr_z - box_state["start_z"]
                    x_move, y_move, z_move = abs(dx_total), abs(dy_total), abs(dz_total)

                    distance_trigger = (z_move > 0.09) or (x_move > 0.12) or (y_move > 0.12)
                    should_judge = (elapsed >= max_punch_time) or \
                                   (elapsed >= min_punch_time and (speed < speed_end * 2.0 or distance_trigger))
                    
                    if should_judge:
                        # ===== 공통 손 이동 필터 =====
                        total_move = (x_move**2 + y_move**2 + z_move**2) ** 0.5

                        hand_moved_enough = (
                            total_move >= MIN_HAND_MOVE and
                            speed >= MIN_HAND_SPEED
                        )

                        if not hand_moved_enough:
                            final_attack = "none"
                        else:
                            # 판정 우선순위
                            hand_started_low = box_state["start_y"] > (active_shldr.y + 0.05)

                            uppercut_like = (
                                dy_total < -0.06
                                and y_move >= x_move * 1.4
                                and y_move >= z_move * 1.3
                                and elbow_ang < uppercut_elbow_max
                                and y_move > 0.07
                                and speed > 0.015
                                and hand_started_low
                                and hand_moved_enough
                            )

                            hook_like = (
                                x_move > 0.09
                                and x_move >= y_move * 1.5
                                and x_move >= z_move * 1.4
                                and speed > 0.015
                                and hand_moved_enough
                            )

                            forward_push = dz < -0.01   # 프레임 기준 전진
                            forward_speed = abs(dz) / max(elapsed, 0.001)
                            
                            # Hand must be in front of shoulder (relative check)
                            hand_forward_relative = (curr_z - active_shldr.z) < -0.03

                            straight_like = (
                                dz_total < -MIN_FORWARD_DZ
                                and z_move >= x_move * 1.3
                                and z_move >= y_move * 1.3
                                and z_move > MIN_FORWARD_DZ
                                and forward_push                 # 🔒 실제 팔 전진
                                and forward_speed > MIN_FORWARD_SPEED
                                and elbow_ang > 155          # 🔒 Straight requires arm extension
                                and hand_forward_relative    # 🔒 Hand must be ahead of shoulder
                                and hand_moved_enough
                            )

                            jab_like = (
                                dz_total < -0.04
                                and z_move > 0.06
                                and elapsed < 0.28
                                and forward_push                 # 🔒
                                and forward_speed > 0.015        # 🔒 더 빠르게
                                and hand_forward_relative        # 🔒 Added relative check
                                and hand_moved_enough
                            )

                            if uppercut_like:
                                final_attack = "uppercut"
                            elif hook_like:
                                final_attack = "hook"
                            elif straight_like:
                                final_attack = "straight"
                            elif jab_like:
                                final_attack = "jab"

                        # ❗ 공격이 성립 안 되면 FAIL은 '이벤트'만, 공격 아님
                        if final_attack == "none":
                            final_attack = "none"

                        # 공격 시도조차 없었으면 데미지 금지 (안전 장치)
                        if not attack_attempted:
                            final_attack = "none"

                        # ❗ 실제 공격일 때만 chance 소모
                        if final_attack in ("jab", "straight", "hook", "uppercut"):
                            chance_consumed = True

                        # 실제 공격 or 타임아웃에서만 종료
                        if final_attack in ("jab", "straight", "hook", "uppercut", "fail"):
                            reset_chance_fsm()

            # 일반 모드 가드/위빙
            if not chance_requested and final_attack == "none":
                is_punch_like = speed > speed_threshold and elbow_ang > extended_angle
                if abs(head_x) > 0.18 and not is_punch_like:
                    if last_defense != "weaving":
                        last_defense = "weaving"
                        last_defense_time = now_t
                    if now_t - last_defense_time >= defense_hold:
                        final_attack = "weaving"
                elif is_guarding and not is_punch_like:
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
        status_msg = "ANALYZING..." if chance_phase == "analyzing" else ("READY" if chance_phase == "ready" else "")
        if status_msg:
            cv2.putText(frame, status_msg, (10, 40), 1, 1.5, (0, 255, 255), 2)
        if box_state["active"]:
            cv2.putText(frame, "START", (10, 70), 1, 1.5, (0, 255, 0), 2)
        cv2.putText(frame, f"chance={chance_requested} active={box_state['active']} consumed={chance_consumed}", (10, 120), 1, 1.1, (255, 0, 255), 2)
        if final_attack != "none":
            cv2.putText(frame, f"ACTION: {final_attack.upper()}", (10, 100), 1, 2.5, (0, 0, 255), 3)

        if chance_requested and chance_phase == "idle":
            print("[FSM ERROR] chance_requested=True but phase=idle")

        cv2.imshow("Motion Debug", frame)
        if cv2.waitKey(1) & 0xFF == 27: break

        if final_attack in ("jab", "straight", "hook", "uppercut"):
            socketio.emit("motion", {"x": round(head_x,3), "z": round(guard_val,3), "dir": final_attack, "t": time.time()})
            last_send_time = time.time()
        elif time.time() - last_send_time > 0.05:
            socketio.emit("motion", {"x": round(head_x,3), "z": round(guard_val,3), "dir": final_attack, "t": time.time()})
            last_send_time = time.time()

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    threading.Thread(target=run_vision, daemon=True).start()
    socketio.run(app, host="127.0.0.1", port=65432, debug=False)
