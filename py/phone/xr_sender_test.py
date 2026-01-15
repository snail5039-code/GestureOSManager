# xr_sender_test.py
import socket, json, time, math

HOST = "127.0.0.1"
PORT = 39500

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

t0 = time.time()
tap_every = 3.0  # 3초마다 탭 한번

while True:
    t = time.time() - t0

    # 원 궤적으로 이동
    x = 0.5 + 0.35 * math.cos(t)
    y = 0.5 + 0.35 * math.sin(t)

    # 가끔 탭
    gesture = "NONE"
    if (t % tap_every) < 0.02:
        gesture = "PINCH_TAP"

    msg = {
        "type": "XR_INPUT",
        "pointerX": x,
        "pointerY": y,
        "tracking": True,
        "gesture": gesture,
    }

    sock.sendto(json.dumps(msg).encode("utf-8"), (HOST, PORT))
    time.sleep(1/60)
