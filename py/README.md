# GestureOS Agent (Refactored)

This is a refactor of the original single-file `agent.py` into a small package with a single entrypoint: `main.py`.

## Folder layout

```
py/
  main.py
  gestureos_agent/
    config.py
    ws_client.py
    gestures.py
    control.py
    mathutil.py
    timeutil.py
    agents/
      hands_agent.py
      color_rush_agent.py
    modes/
      mouse.py
      keyboard.py
      draw.py
      presentation.py
      vkey.py
      ui_menu.py
      rush_lr.py
```

## Run

From the `py/` folder:

- Hands agent (MediaPipe hands → mouse/keyboard/ppt/draw/vkey + rush pointers):
  ```
  python main.py hands
  ```

- Color stick agent (HSV red/blue sticks → rush pointers):
  ```
  python main.py color
  ```

Common flags:
- `--no-ws` / `--no-inject` / `--headless`
- `--start-enabled`, `--start-keyboard`, `--start-rush`, `--start-vkey`
- `--cursor-left`

Example:
```
python main.py hands --start-enabled --start-vkey
```
