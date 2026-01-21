from flask import Flask, Response
import time
import numpy as np
import cv2
import mss

app = Flask(__name__)

FPS = 20
JPEG_QUALITY = 70

# ✅ 스트리밍할 모니터 (1=첫 모니터, 2=두번째...)
MONITOR_INDEX = 1

def gen():
    frame_dt = 1.0 / FPS
    with mss.mss() as sct:
        mon = sct.monitors[MONITOR_INDEX]  # {"left","top","width","height",...}
        next_t = time.time()
        while True:
            now = time.time()
            if now < next_t:
                time.sleep(next_t - now)
            next_t = time.time() + frame_dt

            img = np.array(sct.grab(mon))  # BGRA
            frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if not ok:
                continue

            data = jpg.tobytes()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(data)).encode() + b"\r\n\r\n" +
                   data + b"\r\n")

@app.get("/mjpeg")
def mjpeg():
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    # 방화벽: TCP 8081 허용 필요할 수 있음
    app.run(host="0.0.0.0", port=8081, threaded=True)
