from typing import List, Tuple, Optional
from .mathutil import dist_xy

# MediaPipe Hands landmark: list[(x,y,z)] length 21
LM = List[Tuple[float, float, float]]

def finger_extended(lm: LM, tip: int, pip: int) -> bool:
    # tip y가 pip y보다 위(작음)면 펴짐
    return lm[tip][1] < lm[pip][1]

def is_fist(lm: LM) -> bool:
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    folded = 0
    for t, p in zip(tips, pips):
        if lm[t][1] > lm[p][1]:
            folded += 1
    return folded >= 3

def is_open_palm(lm: LM) -> bool:
    idx = finger_extended(lm, 8, 6)
    mid = finger_extended(lm, 12, 10)
    ring = finger_extended(lm, 16, 14)
    pinky = finger_extended(lm, 20, 18)
    return idx and mid and ring and pinky

def is_pinch_index(lm: LM, thresh: float = 0.06) -> bool:
    return dist_xy((lm[4][0], lm[4][1]), (lm[8][0], lm[8][1])) < thresh

def is_two_finger(lm: LM) -> bool:
    idx = finger_extended(lm, 8, 6)
    mid = finger_extended(lm, 12, 10)
    ring = finger_extended(lm, 16, 14)
    pinky = finger_extended(lm, 20, 18)
    return idx and mid and (not ring) and (not pinky)

def is_v_sign(lm: LM) -> bool:
    if not is_two_finger(lm):
        return False
    return dist_xy((lm[8][0], lm[8][1]), (lm[12][0], lm[12][1])) > 0.06

def is_knife_hand(lm: LM) -> bool:
    # open palm + fingers close together
    if not is_open_palm(lm):
        return False
    d1 = dist_xy((lm[8][0], lm[8][1]), (lm[12][0], lm[12][1]))
    d2 = dist_xy((lm[12][0], lm[12][1]), (lm[16][0], lm[16][1]))
    d3 = dist_xy((lm[16][0], lm[16][1]), (lm[20][0], lm[20][1]))
    avg = (d1 + d2 + d3) / 3.0
    if avg > 0.055:
        return False
    if dist_xy((lm[4][0], lm[4][1]), (lm[5][0], lm[5][1])) > 0.095:
        return False
    return True

def classify_gesture(lm: Optional[LM], pinch_thresh: float = 0.06) -> str:
    if lm is None:
        return "NONE"
    if is_fist(lm):
        return "FIST"
    if is_pinch_index(lm, pinch_thresh):
        return "PINCH_INDEX"
    if is_v_sign(lm):
        return "V_SIGN"
    if is_knife_hand(lm):
        return "KNIFE"
    if is_open_palm(lm):
        return "OPEN_PALM"
    return "OTHER"

def palm_center(lm: LM) -> Tuple[float, float]:
    idx = [0, 5, 9, 13, 17]
    xs = [lm[i][0] for i in idx]
    ys = [lm[i][1] for i in idx]
    return (sum(xs) / len(xs), sum(ys) / len(ys))
