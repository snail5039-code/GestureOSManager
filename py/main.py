"""
GestureOS Agent - refactored multi-file entrypoint.

Usage (Windows):
  python main.py hands
  python main.py color

Common flags (compatible with the original single-file agent.py):
  --headless        : no preview window
  --no-ws           : do not connect to Spring WS
  --no-inject       : do not inject OS mouse/keyboard (still sends STATUS/events)
  --start-enabled   : start enabled=true (otherwise enabled=false)
  --start-keyboard  : start in KEYBOARD mode
  --start-rush      : start in RUSH mode (hands agent only; it disables OS inject)
  --start-vkey      : start in VKEY mode
  --cursor-left     : use Left hand as cursor hand (default Right)

Agent selection:
  - positional: "hands" or "color"
  - or --agent hands|color
"""
from gestureos_agent.config import parse_cli
from gestureos_agent.agents.hands_agent import HandsAgent
from gestureos_agent.agents.color_rush_agent import ColorRushAgent

def main():
    agent_kind, cfg = parse_cli()
    if agent_kind == "color":
        ColorRushAgent(cfg).run()
    else:
        HandsAgent(cfg).run()

if __name__ == "__main__":
    main()
