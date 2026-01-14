import os, cv2, numpy as np

DIR = r"gestureos_agent/assets/reticle"
TARGET = 48
files = ["mouse.png","keyboard.png","draw.png","ppt.png","rush.png"]

if not os.path.isdir(DIR):
    raise SystemExit(f"[ERR] folder not found: {DIR}")

for fn in files:
    p = os.path.join(DIR, fn)
    img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if img is None:
        print("skip(not found or unreadable):", p)
        continue

    # ensure 4-channel BGRA
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        b,g,r = cv2.split(img)
        a = np.full((img.shape[0], img.shape[1]), 255, dtype=img.dtype)
        img = cv2.merge([b,g,r,a])

    h, w = img.shape[:2]
    scale = min(TARGET / w, TARGET / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(img, (nw, nh), interpolation=interp)

    canvas = np.zeros((TARGET, TARGET, 4), dtype=resized.dtype)  # transparent
    x0 = (TARGET - nw) // 2
    y0 = (TARGET - nh) // 2
    canvas[y0:y0+nh, x0:x0+nw] = resized

    # --- 핵심: 보라색(마젠타) 섞임 방지 ---
    # 1) 반투명 제거(가장 확실): 알파가 있으면 255로 올림, 없으면 0
    a = canvas[:, :, 3]
    canvas[:, :, 3] = np.where(a > 0, 255, 0).astype(canvas.dtype)

    # 2) 완전 투명 픽셀의 RGB를 마젠타로 맞춰서 프린지 최소화
    canvas[a == 0, :3] = (255, 0, 255)  # BGR 마젠타

    cv2.imwrite(p, canvas, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    print("ok:", fn, (w,h), "->", (TARGET,TARGET))

print("done")
