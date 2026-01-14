# gestureos_agent/cursor_system.py
import os
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

HCURSOR = wintypes.HANDLE
HINSTANCE = wintypes.HANDLE

SPI_SETCURSORS = 0x0057

# Windows OCR_* cursor IDs (대표적으로 자주 쓰이는 것들)
CURSOR_IDS = [
    32512,  # OCR_NORMAL
    32513,  # OCR_IBEAM
    32514,  # OCR_WAIT
    32515,  # OCR_CROSS
    32516,  # OCR_UP
    32640,  # OCR_SIZE
    32641,  # OCR_ICON
    32642,  # OCR_SIZENWSE
    32643,  # OCR_SIZENESW
    32644,  # OCR_SIZEWE
    32645,  # OCR_SIZENS
    32646,  # OCR_SIZEALL
    32648,  # OCR_NO
    32649,  # OCR_HAND
    32650,  # OCR_APPSTARTING
    32651,  # OCR_HELP
]

# prototypes
user32.CreateCursor.restype = HCURSOR
user32.CreateCursor.argtypes = [
    HINSTANCE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_void_p
]

user32.SetSystemCursor.restype = wintypes.BOOL
user32.SetSystemCursor.argtypes = [HCURSOR, wintypes.DWORD]

user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]

user32.DestroyCursor.restype = wintypes.BOOL
user32.DestroyCursor.argtypes = [HCURSOR]


def _make_invisible_cursor(size: int = 32) -> HCURSOR:
    """
    CreateCursor용 AND/XOR 마스크로 '완전 투명' 커서를 만든다.
    (모노크롬 커서 규칙: AND=1, XOR=0 => 투명)
    """
    w = h = int(size)
    row_bytes = (w + 7) // 8          # 32 => 4 bytes/row
    buf_len = row_bytes * h           # 4*32 = 128

    AND = (ctypes.c_ubyte * buf_len)(*([0xFF] * buf_len))  # 모두 1 => 투명
    XOR = (ctypes.c_ubyte * buf_len)(*([0x00] * buf_len))  # 모두 0

    hcur = user32.CreateCursor(None, 0, 0, w, h,
                               ctypes.cast(AND, ctypes.c_void_p),
                               ctypes.cast(XOR, ctypes.c_void_p))
    if not hcur:
        raise RuntimeError("CreateCursor failed")
    return hcur


def apply_invisible_cursor(debug: bool = False) -> bool:
    """
    시스템 커서를 코드 생성 '완전 투명 커서'로 덮어쓴다.
    중요: SetSystemCursor는 성공 시 핸들을 OS가 소유하므로, cursor id마다 새로 생성해서 넣는다.
    """
    if os.name != "nt":
        return False

    ok_any = False
    for cid in CURSOR_IDS:
        hcur = _make_invisible_cursor(32)

        ok = bool(user32.SetSystemCursor(hcur, cid))
        ok_any = ok_any or ok

        if debug:
            print(f"[CURSOR] SetSystemCursor cid={cid} ok={ok}", flush=True)

        # 성공하면 OS가 소유. 실패하면 우리가 정리.
        if not ok:
            try:
                user32.DestroyCursor(hcur)
            except Exception:
                pass

    return ok_any


def restore_system_cursors():
    """윈도우 기본 커서 세트로 복구"""
    if os.name != "nt":
        return
    user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)
