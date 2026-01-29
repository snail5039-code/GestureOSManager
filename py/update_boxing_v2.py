import os

file_path = r'd:\mwg\Team_Project\GestureOSManager\py\boxing_controller.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the start of the Chance Time Logic
start_idx = -1
for i, line in enumerate(lines):
    if 'if chance_requested and not chance_consumed:' in line:
        start_idx = i
        break

if start_idx == -1:
    print("Could not find start of Chance Time Logic")
    exit(1)

# Find the end of the pose processing block (before screen debugging)
end_idx = -1
for i in range(start_idx, len(lines)):
    if '# 화면 디버깅' in lines[i]:
        end_idx = i
        break

if end_idx == -1:
    print("Could not find end of pose processing block")
    exit(1)

new_logic = """            # ===============================
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

                        # HARD BLOCK
                        if total_move < 0.065 or speed < 0.018:
                            attack_type = "none"
                        else:
                            # Uppercut > Hook > Straight > Jab
                            if dy < -0.12 and abs(dz) < 0.08 and abs(dx) < 0.20 and speed > 0.02 and total_move > 0.08:
                                attack_type = "uppercut"
                            elif abs(dx) > 0.18 and abs(dy) < 0.08 and abs(dz) < 0.06 and speed > 0.02 and total_move > 0.10:
                                attack_type = "hook"
                            elif dz <= -0.12 and total_move > 0.10 and abs(dy) < 0.07 and abs(dx) < 0.18 and speed > 0.02:
                                attack_type = "straight"
                            elif -0.10 < dz < -0.06 and total_move < 0.10 and speed > 0.028 and abs(dy) < 0.05 and abs(dx) < 0.18:
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
"""

# Replace the block
lines[start_idx:end_idx] = [new_logic + '\n']

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Successfully updated boxing_controller.py with optimized logic")
