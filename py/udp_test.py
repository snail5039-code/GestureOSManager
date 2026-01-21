# udp_test.py
import socket, json, time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("3초 안에 메모장을 클릭해서 포커스 주세요...")
time.sleep(3)  # ✅ 이 시간 안에 메모장으로 Alt+Tab 후 클릭

# TEXT: "hello " 타이핑
sock.sendto(
    json.dumps({"type": "XR_TEXT", "text": "hello "}).encode("utf-8"),
    ("127.0.0.1", 39500)
)

# KEY: ENTER 한 번 누르기
sock.sendto(
    json.dumps({"type": "XR_KEY", "key": "ENTER", "action": "TAP"}).encode("utf-8"),
    ("127.0.0.1", 39500)
)

# TEXT: "world" 타이핑
sock.sendto(
    json.dumps({"type": "XR_TEXT", "text": "world"}).encode("utf-8"),
    ("127.0.0.1", 39500)
)

print("sent")
