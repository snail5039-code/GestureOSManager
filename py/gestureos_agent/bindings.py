# file: py/gestureos_agent/bindings.py
from __future__ import annotations

import copy
from typing import Any, Dict


ALLOWED_GESTURES = {
    "NONE",
    "OTHER",
    "OPEN_PALM",
    "PINCH_INDEX",
    "V_SIGN",
    "FIST",
}


DEFAULT_SETTINGS: Dict[str, Any] = {
    "version": 1,
    "bindings": {
        "MOUSE": {
            "MOVE": "OPEN_PALM",
            "CLICK_DRAG": "PINCH_INDEX",
            "RIGHT_CLICK": "V_SIGN",
            "LOCK_TOGGLE": "FIST",
            "SCROLL_HOLD": "FIST",  # other-hand hold
        },
        "KEYBOARD": {
            "BASE": {
                "LEFT": "FIST",
                "RIGHT": "V_SIGN",
                "UP": "PINCH_INDEX",
                "DOWN": "OPEN_PALM",
            },
            "FN": {
                "BACKSPACE": "FIST",
                "SPACE": "OPEN_PALM",
                "ENTER": "PINCH_INDEX",
                "ESC": "V_SIGN",
            },
            "FN_HOLD": "PINCH_INDEX",  # other-hand gate
        },
        "PRESENTATION": {
            "NAV": {
                "NEXT": "PINCH_INDEX",
                "PREV": "V_SIGN",
            },
            "INTERACT": {
                "TAB": "FIST",
                "SHIFT_TAB": "V_SIGN",
                "ACTIVATE": "PINCH_INDEX",
                "PLAY_PAUSE": "OPEN_PALM",
            },
            "INTERACT_HOLD": "FIST",  # other-hand gate
        },
    },
}


def deep_copy(d: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(d)


def _sanitize_gesture(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    if s in ALLOWED_GESTURES:
        return s
    return None


def merge_settings(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merge (best-effort) incoming settings into base.

    Accepts either full settings {version, bindings} or bindings-only {...}.
    Unknown keys are ignored.
    Invalid gesture strings are ignored.
    """
    if not isinstance(incoming, dict):
        return deep_copy(base)

    # normalize shape
    if "bindings" in incoming and isinstance(incoming.get("bindings"), dict):
        inc_bindings = incoming.get("bindings")
        version = incoming.get("version", base.get("version", 1))
    else:
        inc_bindings = incoming
        version = base.get("version", 1)

    out = deep_copy(base)
    out["version"] = int(version) if str(version).isdigit() else out.get("version", 1)

    b = out.get("bindings")
    if not isinstance(b, dict):
        out["bindings"] = {}
        b = out["bindings"]

    for mode, mode_map in (inc_bindings or {}).items():
        if not isinstance(mode_map, dict):
            continue
        mode_u = str(mode).strip().upper()
        if mode_u not in b or not isinstance(b.get(mode_u), dict):
            b[mode_u] = {}
        for k, v in mode_map.items():
            key_u = str(k).strip().upper()

            # nested blocks (e.g., KEYBOARD.BASE)
            if isinstance(v, dict):
                if key_u not in b[mode_u] or not isinstance(b[mode_u].get(key_u), dict):
                    b[mode_u][key_u] = {}
                for kk, vv in v.items():
                    kk_u = str(kk).strip().upper()
                    g = _sanitize_gesture(vv)
                    if g is not None:
                        b[mode_u][key_u][kk_u] = g
                continue

            g = _sanitize_gesture(v)
            if g is not None:
                b[mode_u][key_u] = g

    return out


def get_binding(settings: Dict[str, Any], *path: str, default: str) -> str:
    """Read nested binding value safely."""
    cur: Any = settings.get("bindings", {}) if isinstance(settings, dict) else {}
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    if isinstance(cur, str):
        v = _sanitize_gesture(cur)
        return v or default
    return default
