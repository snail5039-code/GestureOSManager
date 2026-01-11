import cv2

aruco = cv2.aruco
aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)

def save_marker(marker_id, size=700, path="marker.png"):
    # OpenCV 버전에 따라 함수명이 다를 수 있어 안전하게 처리
    if hasattr(aruco, "generateImageMarker"):
        img = aruco.generateImageMarker(aruco_dict, marker_id, size)
    else:
        img = aruco.drawMarker(aruco_dict, marker_id, size)

    ok = cv2.imwrite(path, img)
    if not ok:
        raise RuntimeError(f"Failed to write: {path}")

save_marker(0, 700, "aruco_0.png")  # RIGHT
save_marker(1, 700, "aruco_1.png")  # LEFT
print("saved aruco_0.png, aruco_1.png")
