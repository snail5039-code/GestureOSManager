import os

file_path = r'd:\mwg\Team_Project\GestureOSManager\py\boxing_controller.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the start of the attack classification block
start_idx = -1
for i, line in enumerate(lines):
    if '# HARD BLOCK' in line:
        # Check if the next line is the total_move check
        if i + 1 < len(lines) and 'if total_move < 0.065 or speed < 0.018:' in lines[i+1]:
            start_idx = i
            break

if start_idx == -1:
    print("Could not find start of attack classification block")
    exit(1)

# Find the end of the classification block (before the if attack_type != "none":)
end_idx = -1
for i in range(start_idx, len(lines)):
    if 'if attack_type != "none":' in lines[i]:
        end_idx = i
        break

if end_idx == -1:
    print("Could not find end of attack classification block")
    exit(1)

new_classifier = """                        # =========================
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
"""

# Replace the block
lines[start_idx:end_idx] = [new_classifier + '\n']

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Successfully updated boxing_controller.py with strict priority hotfix")
