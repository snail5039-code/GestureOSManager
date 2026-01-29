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

MIN_HAND_MOVE = 0.035        # 손 최소 총 이동량 (Relaxed)
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

def reset_chance_fsm(hard=True):
    global chance_active, chance_requested, chance_phase
    global chance_consumed, attack_attempted, intent_counter
    global box_state, ready_to_active_counter, active_ambiguous_counter, static_active_counter

    if hard:
        chance_active = False
        chance_requested = False
        chance_phase = "idle"
    
    chance_consumed = False
    attack_attempted = False
    intent_counter = 0
    ready_to_active_counter = 0
    active_ambiguous_counter = 0
    static_active_counter = 0

    box_state = {
        "active": False,
        "hand": None,
        "path_x": [], "path_y": [], "path_z": [],
        "start_x": 0, "start_y": 0, "start_z": 0,
        "start_time": 0,
        "max_dx": 0, "max_dy": 0, "max_dz": 0,
        "min_y": 0.0,
    }
    # 🔒 Clear Neutral Pose
    neutral_hand["init"] = False

chance_requested = False
force_attack_mode = False
chance_phase = "idle"  # "idle" | "ready" | "analyzing"
chance_consumed = False
chance_start_time = 0.0
attack_attempted = False
intent_counter = 0
ready_to_active_counter = 0  # 🔥 Consecutive frames for ACTIVE entry
INTENT_SPEED = 0.012
REQUIRED_INTENT_FRAMES = 3  # 🔥 Unified intent frames
just_failed = False  # 🔥 Prevent duplicate emits in same frame
active_ambiguous_counter = 0
active_enter_time = 0.0
last_active_exit_time = 0.0
static_active_counter = 0

prev_hand = {
    "left": {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0, "init": False},
    "right": {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0, "init": False},
}
prev_shoulder = {
    "left": {"z": 0.0, "init": False},
    "right": {"z": 0.0, "init": False},
}
# 🔒 Neutral Pose for Chance Time
neutral_hand = {
    "x": 0.0, "y": 0.0, "z": 0.0,
    "init": False
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
        ready_to_active_counter = 0
        active_ambiguous_counter = 0
        static_active_counter = 0
        chance_start_time = time.time()
        return
    chance_requested = bool(data.get("active")) 
    chance_active = chance_requested
    if chance_requested:
        chance_phase = "ready"  # 🔒 Start in READY phase
        chance_consumed = False
        attack_attempted = False
        intent_counter = 0
        ready_to_active_counter = 0
        active_ambiguous_counter = 0
        static_active_counter = 0
        chance_start_time = time.time()
        neutral_hand["init"] = False  # 🔒 Force re-capture
    else:
        chance_phase = "idle"
        chance_consumed = False
        box_state["active"] = False
        box_state["path_x"] = []
        box_state["path_y"] = []
        box_state["path_z"] = []
        reset_chance_fsm() # 🔥 Reset when front signal ends

def run_vision():
    global box_state, chance_active, chance_requested, prev_hand, prev_shoulder, last_jab_valid_ts, chance_phase, chance_consumed, chance_start_time, attack_attempted, intent_counter, ready_to_active_counter, just_failed, active_ambiguous_counter, active_enter_time, last_active_exit_time, static_active_counter
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
        now_t = time.time()
        final_attack = "none"
        just_failed = False  # 🔥 Reset each frame
        success, frame = cap.read()
        if not success:
            continue
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = pose.process(rgb)

        # FSM Auto-Recovery removed for strict FSM discipline
        head_x, guard_val = 0.0, 0.0

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

            # Update Jab Optimization (Disabled during Chance)
            if not chance_requested:
                jab_signal = -dz if dz < 0 else 0
                if update_jab(jab_signal, now_t):
                    last_jab_valid_ts = now_t

            # 🔒 Chance Time Logic (Guard does NOT block chance)
            # 🔒 Chance Time Logic (Guard does NOT block chance)
            # ===============================
            # 🔹 Chance ACTIVE 통합판 (AntiGravity 최적화)
            # ===============================
            if chance_requested and not chance_consumed:
                if chance_phase == "ready":
                    # Neutral capture
                    if not neutral_hand["init"]:
                        neutral_hand["x"] = curr_x
                        neutral_hand["y"] = curr_y
                        neutral_hand["z"] = curr_z
                        neutral_hand["init"] = True
                        print(f"[FSM] READY: Neutral Captured ({curr_x:.2f}, {curr_y:.2f}, {curr_z:.2f})")

                    dz_n = curr_z - neutral_hand["z"]
                    dy_n = curr_y - neutral_hand["y"]
                    z_enter_thresh = 0.09
                    uppercut_y_thresh = -0.12
                    ready_cooldown = 0.45

                    if ((dz_n < -z_enter_thresh or dy_n < uppercut_y_thresh)
                        and (now_t - last_active_exit_time > ready_cooldown)):
                        ready_to_active_counter += 1
                        if ready_to_active_counter >= 2:  # 연속 2프레임
                            chance_phase = "active"
                            intent_counter = 0
                            attack_attempted = False
                            active_enter_time = now_t
                            active_ambiguous_counter = 0
                            static_active_counter = 0
                            print("[FSM] READY -> ACTIVE (Z/Y ENTER)")
                    else:
                        ready_to_active_counter = 0

                elif chance_phase == "active":
                    dx = curr_x - neutral_hand["x"]
                    dy = curr_y - neutral_hand["y"]
                    dz = curr_z - neutral_hand["z"]
                    total_move = (dx**2 + dy**2 + dz**2) ** 0.5

                    # 🔒 거의 정지 상태 차단
                    if total_move < 0.065 and speed < 0.018:
                        intent_counter = 0

                    # 🔒 미세 움직임/유령 제거
                    if speed < 0.008 and total_move < 0.03:
                        intent_counter = 0
                    if abs(head_x) > 0.25 and total_move < 0.05:
                        intent_counter = max(0, intent_counter - 1)
                    if total_move < 0.025 and speed < 0.012:
                        intent_counter = max(0, intent_counter - 1)

                    # Hand leads body
                    shoulder_move = abs(active_shldr.z - prev_shoulder["left" if is_left else "right"]["z"])
                    hand_leads = (abs(dz) > shoulder_move * 0.8 or abs(dx) > 0.10 or abs(dy) > 0.08)

                    base_intent = total_move > 0.065 and speed > 0.018 and hand_leads
                    uppercut_intent = base_intent and dy < -0.09
                    lateral_intent = base_intent and abs(dx) > 0.10 and abs(dx) > abs(dz) * 0.7
                    forward_intent = base_intent and dz < -0.06 and abs(dx) < 0.18 and abs(dy) < 0.12

                    is_attack_intent = uppercut_intent or lateral_intent or forward_intent
                    if is_attack_intent:
                        if abs(head_x) > 0.35:  # Weaving block
                            intent_counter = max(0, intent_counter - 1)
                        else:
                            intent_counter += 1
                    else:
                        intent_counter = max(0, intent_counter - 1)

                    # 🔥 최소 3프레임 누적 필요
                    if intent_counter >= REQUIRED_INTENT_FRAMES:
                        attack_type = "none"

                        # =========================
                        # 🔥 STRICT PRIORITY ATTACK CLASSIFIER (HOTFIX)
                        # Uppercut > Hook > Straight > Jab
                        # =========================

                        attack_type = "none"

                        # 공통 하드 게이트
                        if total_move < 0.08 or speed < 0.02:
                            attack_type = "none"
                        else:
                            # 1️⃣ UPPERCUT (dy 최우선 + dx/dz 강제 억제)
                            if (
                                dy < -0.14 and              # 🔥 더 강한 상향
                                abs(dx) < 0.14 and          # 🔥 좌우 억제
                                abs(dz) < 0.10 and          # 🔥 전진 억제
                                speed > 0.022 and
                                total_move > 0.09
                            ):
                                attack_type = "uppercut"

                            # 2️⃣ HOOK (dx 최우선 + dy 상향 배제)
                            elif (
                                abs(dx) > 0.20 and
                                abs(dy) < 0.07 and          # 🔥 uppercut 완전 배제
                                abs(dz) < 0.08 and
                                speed > 0.022 and
                                total_move > 0.11
                            ):
                                attack_type = "hook"

                            # 3️⃣ STRAIGHT (dz 최우선 + dx/dy 억제)
                            elif (
                                dz < -0.14 and
                                abs(dx) < 0.14 and
                                abs(dy) < 0.08 and
                                speed > 0.022 and
                                total_move > 0.11
                            ):
                                attack_type = "straight"

                            # 4️⃣ JAB (약한 straight 전용)
                            elif (
                                -0.11 < dz < -0.07 and
                                abs(dx) < 0.16 and
                                abs(dy) < 0.06 and
                                speed > 0.028 and
                                total_move < 0.11
                            ):
                                attack_type = "jab"

                        if attack_type != "none":
                            final_attack = attack_type
                            attack_attempted = True
                            chance_phase = "consumed"
                            chance_consumed = True
                            print(f"[FSM] ACTIVE -> CONSUMED: {final_attack}")
                            socketio.emit("motion", {"dir": final_attack, "t": time.time()})
                            reset_chance_fsm()
                        else:
                            # ambiguous 처리
                            intent_counter = max(0, intent_counter - 1)
                            active_ambiguous_counter += 1
                            if active_ambiguous_counter > 8:
                                print("[FSM] AMBIGUOUS -> FAIL -> EXIT CHANCE")
                                socketio.emit("motion", {"dir": "fail", "t": time.time()})
                                reset_chance_fsm()

                    # ACTIVE TIMEOUT 0.9s
                    if now_t - active_enter_time > 0.9:
                        print("[FSM] ACTIVE TIMEOUT -> READY")
                        chance_phase = "ready"
                        intent_counter = 0
                        active_ambiguous_counter = 0
                        static_active_counter = 0
                        last_active_exit_time = now_t

                elif chance_phase == "consumed":
                    pass

            # 일반 모드 가드/위빙 (chance 아닐 때만)
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

        # 🔒 Strict Timeout Handling
        if chance_requested and not chance_consumed:
            if now_t - chance_start_time > 1.2:
                safe_total_move = total_move if 'total_move' in locals() else 0.0
                if intent_counter > 0 and safe_total_move > 0.04:
                    print("[FSM] ATTEMPTED BUT WEAK -> FAIL -> EXIT CHANCE")
                    socketio.emit("motion", {"dir": "fail", "t": time.time()})
                else:
                    print("[FSM] TRUE TIMEOUT -> EXIT CHANCE TIME")
                    socketio.emit("motion", {"dir": "timeout", "t": time.time()})

                reset_chance_fsm()
                final_attack = "fail"
                just_failed = True

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

        if not just_failed: # 🔥 Skip if already failed/timeout this frame
            if final_attack in ("jab", "straight", "hook", "uppercut"):
                # 🔒 Chance FSM 중복 전송 차단
                if not (chance_requested and chance_consumed):
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
