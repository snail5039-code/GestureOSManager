import math
from typing import Optional, Tuple

def clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))

def dist_xy(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def ema(prev: Optional[float], cur: float, alpha: float) -> float:
    if prev is None:
        return cur
    return (1.0 - alpha) * prev + alpha * cur
