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
    global neutral_hands

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
    neutral_hands["init"] = False

def exit_chance(reason):
    global chance_phase, chance_requested, chance_active, last_active_exit_time
    # Rule 3: Explicit clearing to ensure return to normal mode
    chance_requested = False
    chance_active = False
    chance_phase = "idle"
    
    # 🔒 Rule: Pulsing exit time to prevent immediate re-entry loop
    last_active_exit_time = time.time()
    
    print(f"[FSM] EXIT CHANCE: {reason}")
    
    # Rule 1 & 4: Chance FSM reports its own terminal results without hijacking final_attack
    if reason in ("fail", "timeout"):
        socketio.emit("motion", {"dir": reason, "t": time.time()})
        
    socketio.emit("chance_end", {"reason": reason, "t": time.time()})
    reset_chance_fsm(hard=True)

chance_requested = False
force_attack_mode = False
chance_phase = "idle"  # "idle" | "ready" | "analyzing"
chance_consumed = False
chance_start_time = 0.0
attack_attempted = False
intent_counter = 0
ready_to_active_counter = 0  # 🔥 Consecutive frames for ACTIVE entry
INTENT_SPEED = 0.012
REQUIRED_INTENT_FRAMES = 2  # 🔥 LOG-based intent frames (relaxed to 2)
just_failed = False  # 🔥 Prevent duplicate emits in same frame
active_ambiguous_counter = 0
active_enter_time = 0.0
last_active_exit_time = 0.0
static_active_counter = 0
CHANCE_TOTAL_TIMEOUT = 2.5  # 🔒 Unified total Chance Time budget (seconds, aligned with front UI)

# ===============================
# Chance Time Attack Classification Tunables
# (Priority: uppercut > hook > straight > jab)
# LOG-based relaxed values
# ===============================
UP_DY = 0.16        # Uppercut: minimum upward Y (relaxed)
UP_DZ_MAX = 0.22    # Uppercut: allow more forward Z
UP_DX_MAX = 0.22    # Uppercut: allow some lateral drift

HOOK_DX = 0.20      # Hook: minimum lateral X (relaxed)
HOOK_DZ_MIN = 0.04  # Hook: minimal forward allowance (info only)
HOOK_DZ_MAX = 0.45  # Hook: allow stronger Z before straight split

STR_DZ = 0.30       # Straight: strong forward Z (relaxed)
STR_DX_MAX = 0.22
STR_DY_MAX = 0.28

JAB_DZ = 0.14       # Jab: weaker forward Z (relaxed)
JAB_DZ_MAX = 0.34
JAB_DX_MAX = 0.18
JAB_DY_MAX = 0.22

MIN_ATTACK_SPEED = 0.018   # Per-attack minimal speed (relaxed from logs)
HARD_MIN_MOVE = 0.035      # Hard block total movement (LOG-based)
HARD_MIN_SPEED = 0.010     # Hard block speed (LOG-based)

prev_hand = {
    "left": {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0, "init": False},
    "right": {"x": 0.0, "y": 0.0, "z": 0.0, "t": 0.0, "init": False},
}
prev_shoulder = {
    "left": {"z": 0.0, "init": False},
    "right": {"z": 0.0, "init": False},
}
last_active_hand = "R"
# 🔒 Neutral Pose for Chance Time (Dual support)
neutral_hands = {
    "L": {"x": 0.0, "y": 0.0, "z": 0.0},
    "R": {"x": 0.0, "y": 0.0, "z": 0.0},
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
    global chance_active, chance_requested, chance_phase, box_state, chance_consumed
    global chance_start_time, attack_attempted, intent_counter, last_active_hand
    global ready_to_active_counter, active_ambiguous_counter, static_active_counter
    global neutral_hands

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

    # 🔒 New contract: one-shot trigger from front ({ chance_trigger: true })
    if "chance_trigger" in data:
        if data.get("chance_trigger"):
            chance_requested = True
            chance_active = True
            chance_phase = "ready"  # Start in READY phase
            chance_consumed = False
            attack_attempted = False
            intent_counter = 0
            ready_to_active_counter = 0
            active_ambiguous_counter = 0
            static_active_counter = 0
            chance_start_time = time.time()
            neutral_hands["init"] = False  # Force re-capture
        # ignore false/zero triggers to avoid front-driven cancellation
        return

    # Legacy path for older clients still using { active: bool }
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
        neutral_hands["init"] = False  # 🔒 Force re-capture
    else:
        chance_phase = "idle"
        chance_consumed = False
        box_state["active"] = False
        box_state["path_x"] = []
        box_state["path_y"] = []
        box_state["path_z"] = []
        reset_chance_fsm() # 🔥 Reset when front signal ends

def run_vision():
    global box_state, chance_active, chance_requested, prev_hand, prev_shoulder
    global last_jab_valid_ts, chance_phase, chance_consumed, chance_start_time
    global attack_attempted, intent_counter, ready_to_active_counter, just_failed
    global active_ambiguous_counter, active_enter_time, last_active_exit_time
    global static_active_counter, last_active_hand, neutral_hands

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[ERROR] Could not open webcam.")
        return
    
    # 🔒 Server binding hint
    print(f"[SERVER] Starting on http://0.0.0.0:65432")
    
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

            # move_L, move_R 계산 (Neutral 대비)
            move_L = 0.0
            move_R = 0.0
            if neutral_hands["init"]:
                move_L = ((lw.x - neutral_hands["L"]["x"])**2 + (lw.y - neutral_hands["L"]["y"])**2 + (lw.z - neutral_hands["L"]["z"])**2)**0.5
                move_R = ((rw.x - neutral_hands["R"]["x"])**2 + (rw.y - neutral_hands["R"]["y"])**2 + (rw.z - neutral_hands["R"]["z"])**2)**0.5

            if chance_requested and chance_phase == "ready":
                if move_L > move_R * 1.15:
                    is_left = True
                    last_active_hand = "L"
                elif move_R > move_L * 1.15:
                    is_left = False
                    last_active_hand = "R"
                else:
                    is_left = (last_active_hand == "L")
            elif chance_requested and chance_phase == "active":
                # 🔒 Rule: ACTIVE 동안 손 재선택 금지 (Lock choice)
                is_left = (last_active_hand == "L")
            else:
                is_left = lw.z < rw.z

            active_hand = lw if is_left else rw
            active_elbow = le if is_left else re
            active_shldr = ls if is_left else rs

            # [HAND] Debug Log
            if chance_requested and chance_phase == "active":
                print(f"[HAND] active={'L' if is_left else 'R'} moveL={move_L:.3f} moveR={move_R:.3f}")

            curr_x, curr_y, curr_z = active_hand.x, active_hand.y, active_hand.z
            dx = l_dx if is_left else r_dx
            dy = l_dy if is_left else r_dy
            dz = l_dz if is_left else r_dz
            speed = l_speed if is_left else r_speed
            elbow_ang = l_angle if is_left else r_angle

            # 가드 판정 (일반 모드에서만)
            left_guard = abs(lw.x - nose.x) < 0.25 and nose.y - 0.05 < lw.y < nose.y + 0.35
            right_guard = abs(rw.x - nose.x) < 0.25 and nose.y - 0.05 < rw.y < nose.y + 0.35
            is_guarding = left_guard and right_guard and abs(head_x) < 0.25

            if chance_requested:
                guard_val = 0.0
            else:
                guard_val = 1.0 if is_guarding else 0.0

            # Update Jab Optimization (Disabled during Chance)
            if not chance_requested:
                # Use normalized dz for jab signal
                jab_signal = -dz if dz < 0 else 0
                if update_jab(jab_signal, now_t):
                    final_attack = "jab"
                    last_jab_valid_ts = now_t
                    print(f"[JAB] Detected at {now_t:.2f}")

                # Rule 2: Restore Defense Pipeline (weaving/guard)
                if final_attack == "none":
                    # Check for punch-like motion to avoid guard/weaving during actual punches
                    is_punch_like = speed > speed_threshold and elbow_ang > extended_angle
                    
                    # Weaving (Head movement)
                    if abs(head_x) > 0.18 and not is_punch_like:
                        if last_defense != "weaving":
                            last_defense = "weaving"
                            last_defense_time = now_t
                        if now_t - last_defense_time >= defense_hold:
                            final_attack = "weaving"
                    # Guard (Hands in front of face)
                    elif is_guarding and not is_punch_like:
                        if last_defense != "guard":
                            last_defense = "guard"
                            last_defense_time = now_t
                        if now_t - last_defense_time >= defense_hold:
                            final_attack = "guard"
                    else:
                        last_defense = "none"

            # 🔒 Chance Time Logic
            if chance_requested and not chance_consumed:
                if chance_phase == "ready":
                    if not neutral_hands["init"]:
                        neutral_hands["L"] = {"x": lw.x, "y": lw.y, "z": lw.z}
                        neutral_hands["R"] = {"x": rw.x, "y": rw.y, "z": rw.z}
                        neutral_hands["init"] = True
                        print(f"[FSM] READY: Dual Neutral Captured")
                    
                    n_pos = neutral_hands["L" if is_left else "R"]
                    dz_n = curr_z - n_pos["z"]
                    dy_n = curr_y - n_pos["y"]
                    # LOG-based relaxed entry to ACTIVE
                    z_enter_thresh = 0.07
                    uppercut_y_thresh = -0.09
                    ready_cooldown = 0.45

                    if ((dz_n < -z_enter_thresh or dy_n < uppercut_y_thresh)
                        and (now_t - last_active_exit_time > ready_cooldown)):
                        ready_to_active_counter += 1
                        if ready_to_active_counter >= 3:
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
                    if now_t - active_enter_time < 0.15:
                        continue

                    n_pos = neutral_hands["L" if is_left else "R"]
                    dx_active = curr_x - n_pos["x"]
                    dy_active = curr_y - n_pos["y"]
                    dz_active = curr_z - n_pos["z"]
                    total_move = (dx_active**2 + dy_active**2 + dz_active**2) ** 0.5
                    norm_dx = -dx_active if is_left else dx_active
                    
                    if chance_requested and chance_phase == "active":
                         print(f"[HAND] active={'L' if is_left else 'R'} dx={dx_active:.3f} norm_dx={norm_dx:.3f} moveL={move_L:.3f} moveR={move_R:.3f}")

                    if total_move < 0.045 and speed < 0.012:
                        intent_counter = max(0, intent_counter - 1)
                    if speed < 0.008 and total_move < 0.03:
                        intent_counter = max(0, intent_counter - 1)
                    if abs(head_x) > 0.25 and total_move < 0.05:
                        intent_counter = max(0, intent_counter - 1)
                    # LOG-based relaxed decay: only when movement & speed are both very small
                    if total_move < 0.025 and speed < 0.008:
                        intent_counter = max(0, intent_counter - 1)

                    base_intent = total_move > HARD_MIN_MOVE and speed > HARD_MIN_SPEED
                    # Uppercut intent aligned with classification (dy_cls vs UP_DY)
                    dy_cls_intent = -(dy_active)
                    uppercut_intent = base_intent and dy_cls_intent > (UP_DY * 0.6)
                    lateral_intent = base_intent and abs(norm_dx) > 0.10 and abs(norm_dx) > abs(dz_active) * 0.7
                    forward_intent = base_intent and dz_active < -0.06 and abs(norm_dx) < 0.18 and abs(dy_active) < 0.12

                    is_attack_intent = uppercut_intent or lateral_intent or forward_intent
                    if is_attack_intent:
                        if abs(head_x) > 0.35:
                            intent_counter = max(0, intent_counter - 1)
                        else:
                            intent_counter += 1
                    else:
                        intent_counter = max(0, intent_counter - 1)

                    if intent_counter >= REQUIRED_INTENT_FRAMES:
                        attack_type = "none"

                        # ==== HARD BLOCK: filter out micro/ghost motions ====
                        if total_move >= HARD_MIN_MOVE and speed >= HARD_MIN_SPEED:
                            # Normalize axes for classification:
                            #  - dx: lateral (positive = outward for each hand)
                            #  - dy: upward positive
                            #  - dz: forward positive
                            dx_cls = norm_dx
                            dy_cls = -dy_active
                            dz_cls = -dz_active

                            # Debug: observe normalized components at classification time
                            print(f"[ATTACK_DEBUG] hand={'L' if is_left else 'R'} "
                                  f"dx={dx_cls:.3f} dy={dy_cls:.3f} dz={dz_cls:.3f} "
                                  f"total={total_move:.3f} speed={speed:.3f}")

                            # Left-hand relaxation (5~10%)
                            up_dy = UP_DY * (0.9 if is_left else 1.0)
                            hook_dx = HOOK_DX * (0.9 if is_left else 1.0)
                            str_dz = STR_DZ * (0.9 if is_left else 1.0)
                            jab_dz = JAB_DZ * (0.9 if is_left else 1.0)

                            # === Priority-based classification ===
                            # 1) UPPERCUT (dy dominant, z small)
                            if (
                                dy_cls > up_dy and
                                abs(dz_cls) < UP_DZ_MAX and
                                abs(dx_cls) < UP_DX_MAX and
                                speed > MIN_ATTACK_SPEED
                            ):
                                attack_type = "uppercut"

                            # 2) HOOK (dx dominant)
                            elif (
                                abs(dx_cls) > hook_dx and
                                abs(dz_cls) < HOOK_DZ_MAX and
                                speed > MIN_ATTACK_SPEED
                           ):
                                attack_type = "hook"

                            # 3) STRAIGHT (strong z, low x/y)
                            elif (
                                abs(dz_cls) > str_dz and
                                abs(dx_cls) < STR_DX_MAX and
                                abs(dy_cls) < STR_DY_MAX and
                                speed > MIN_ATTACK_SPEED
                           ):
                                attack_type = "straight"

                            # 4) JAB (weak z, tighter x/y)
                            elif (
                                jab_dz < abs(dz_cls) < JAB_DZ_MAX and
                                abs(dx_cls) < JAB_DX_MAX and
                                abs(dy_cls) < JAB_DY_MAX and
                                speed > MIN_ATTACK_SPEED
                           ):
                                attack_type = "jab"

                        if attack_type != "none":
                            final_attack = attack_type
                            attack_attempted = True
                            chance_phase = "consumed"
                            chance_consumed = True
                            print(f"[FSM] ACTIVE -> CONSUMED: {final_attack}")
                            # Final attack emission handled by main loop to include coordinates
                            exit_chance("success")
                        else:
                            intent_counter = max(0, intent_counter - 1)
                            active_ambiguous_counter += 1
                            if active_ambiguous_counter > 14:
                                exit_chance("fail")

                    if now_t - active_enter_time > CHANCE_TOTAL_TIMEOUT:
                        exit_chance("timeout")

        # 🔒 Strict Timeout Handling (Unified with exit_chance)
        if chance_requested and not chance_consumed:
            if now_t - chance_start_time > CHANCE_TOTAL_TIMEOUT:
                safe_total_move = total_move if 'total_move' in locals() else 0.0
                if intent_counter > 0 and safe_total_move > 0.04:
                    exit_chance("fail")
                else:
                    exit_chance("timeout")
                # final_attack = "fail" (Forbidden by Rule 1)
                just_failed = True

        # 화면 디버깅
        status_msg = "ANALYZING..." if chance_phase == "analyzing" else ("READY" if chance_phase == "ready" else "")
        if status_msg: cv2.putText(frame, status_msg, (10, 40), 1, 1.5, (0, 255, 255), 2)
        cv2.putText(frame, f"chance={chance_requested} phase={chance_phase}", (10, 120), 1, 1.1, (255, 0, 255), 2)
        if final_attack != "none": cv2.putText(frame, f"ACTION: {final_attack.upper()}", (10, 100), 1, 2.5, (0, 0, 255), 3)

        cv2.imshow("Motion Debug", frame)
        if cv2.waitKey(1) & 0xFF == 27: break

        if not just_failed:
            if final_attack in ("jab", "straight", "hook", "uppercut"):
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
    socketio.run(app, host="0.0.0.0", port=65432, debug=False)