"""매니저 서버(8080)가 기동할 때 만들어 두는 로컬 세션 토큰을 읽는다.

서버는 모든 API 와 WebSocket 접속에 이 토큰을 요구한다. 같은 사용자로 실행되는
프로그램만 파일을 읽을 수 있으므로, 사용자가 열어둔 웹페이지가 이 서버에 붙어
에이전트를 위장하거나 상태를 구독하는 경로가 막힌다.

서버가 재시작되면 토큰이 바뀐다. 그래서 접속을 시도할 때마다 다시 읽는다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit


def token_path() -> Path:
    configured = os.getenv("GOS_TOKEN_PATH")
    if configured:
        return Path(configured)
    return Path.home() / ".gestureos" / "session.token"


def read_token() -> Optional[str]:
    """토큰 문자열, 없으면 None."""
    try:
        value = token_path().read_text(encoding="utf-8").strip()
        return value or None
    except Exception:
        # 서버가 아직 안 떴거나 인증이 꺼진 경우
        return None


def with_token(url: str, token: Optional[str] = None) -> str:
    """WebSocket URL 에 ?token=... 을 붙인다. 토큰이 없으면 URL 을 그대로 돌려준다."""
    tok = token if token is not None else read_token()
    if not tok:
        return url

    parts = urlsplit(url)
    query = parts.query
    extra = urlencode({"token": tok})
    merged = f"{query}&{extra}" if query else extra
    return urlunsplit((parts.scheme, parts.netloc, parts.path, merged, parts.fragment))
