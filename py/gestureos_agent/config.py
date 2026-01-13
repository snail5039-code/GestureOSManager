from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Iterable, Tuple, Optional

DEFAULT_WS_URL = "ws://127.0.0.1:8080/ws/agent"

@dataclass(frozen=True)
class AgentConfig:
    # core toggles
    headless: bool
    no_ws: bool
    no_inject: bool

    start_enabled: bool
    start_keyboard: bool
    start_rush: bool
    start_vkey: bool

    force_cursor_left: bool

    # websocket
    ws_url: str = DEFAULT_WS_URL

    # control mapping (normalized 0~1)
    control_box: tuple = (0.22, 0.28, 0.78, 0.95)
    control_gain: float = 1.10
    control_half_w: float = 0.20
    control_half_h: float = 0.28

    # smoothing / cursor
    ema_alpha: float = 0.22
    deadzone_px: int = 10
    move_hz: float = 60.0

def parse_cli(argv: Optional[Iterable[str]] = None) -> Tuple[str, AgentConfig]:
    """
    Returns: (agent_kind, config)
      agent_kind: "hands" | "color"
    """
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)

    # agent selection: --agent X or first positional token
    agent_kind = "hands"
    for a in argv:
        if a.startswith("--agent="):
            agent_kind = a.split("=", 1)[1].strip().lower()
    if agent_kind not in ("hands", "color"):
        agent_kind = "hands"

    # if user supplied positional like: python main.py color --no-inject
    for a in argv:
        if a.startswith("-"):
            continue
        if a.lower() in ("hands", "color"):
            agent_kind = a.lower()
            break

    args = set([a for a in argv if a.startswith("-")])

    # optional: override websocket url
    ws_url = DEFAULT_WS_URL
    for i, a in enumerate(argv):
        if a.startswith("--ws-url="):
            ws_url = a.split("=", 1)[1].strip()
        elif a == "--ws-url" and i + 1 < len(argv):
            ws_url = str(argv[i + 1]).strip()

    headless = ("--headless" in args)
    no_ws = ("--no-ws" in args)
    no_inject = ("--no-inject" in args)

    start_enabled = ("--start-enabled" in args)
    start_keyboard = ("--start-keyboard" in args)
    start_rush = ("--start-rush" in args)
    start_vkey = ("--start-vkey" in args)

    force_cursor_left = ("--cursor-left" in args)

    cfg = AgentConfig(
        headless=headless,
        no_ws=no_ws,
        no_inject=no_inject,
        start_enabled=start_enabled,
        start_keyboard=start_keyboard,
        start_rush=start_rush,
        start_vkey=start_vkey,
        force_cursor_left=force_cursor_left,
        ws_url=ws_url,
    )
    return agent_kind, cfg
