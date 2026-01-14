# 용량 줄여주는거 png 파일들
import os, cv2, numpy as np

DIR = r"gestureos_agent/assets/reticle"
TARGET = 48
files = ["cursor.png","mouse.png","carrot01.png","cat03.png","cat.png","cat02.png"]

if not os.path.isdir(DIR):
    raise SystemExit(f"[ERR] folder not found: {DIR}")

for fn in files:
    p = os.path.join(DIR, fn)
    img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
    if img is None:
        print("skip(not found or unreadable):", p)
        continue

    # ensure 4-channel BGRA
    if img.shape[2] == 3:
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

    cv2.imwrite(p, canvas)
    print("ok:", fn, (w,h), "->", (TARGET,TARGET))

print("done")
