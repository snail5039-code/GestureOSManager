// 매니저 서버(8080)가 기동할 때 만들어 두는 로컬 세션 토큰을 읽는다.
//
// 서버는 모든 /api 요청과 WebSocket 접속에 이 토큰을 요구한다. 같은 사용자로 실행되는
// 프로그램만 이 파일을 읽을 수 있으므로, 사용자가 열어둔 웹페이지가 로컬 API 를
// 호출하는 경로가 막힌다.
//
// 서버가 재시작되면 토큰이 바뀐다. 그래서 값을 영구 캐시하지 않고 짧게만 캐시하고,
// 401 을 만나면 다시 읽는다.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const DEFAULT_TOKEN_PATH = path.join(os.homedir(), ".gestureos", "session.token");
const CACHE_MS = 2000;

let cached = { value: null, at: 0 };

function tokenPath() {
  return process.env.GOS_TOKEN_PATH || DEFAULT_TOKEN_PATH;
}

/** 토큰 문자열 또는 null(파일이 아직 없으면). */
function readLocalToken() {
  const now = Date.now();
  if (cached.value && now - cached.at < CACHE_MS) return cached.value;

  try {
    const v = fs.readFileSync(tokenPath(), "utf8").trim();
    cached = { value: v || null, at: now };
    return cached.value;
  } catch {
    // 서버가 아직 안 떴거나 인증이 꺼져 있는 경우
    cached = { value: null, at: now };
    return null;
  }
}

/** 401 을 받았을 때처럼, 다음 호출에서 파일을 다시 읽게 한다. */
function invalidateLocalToken() {
  cached = { value: null, at: 0 };
}

module.exports = { readLocalToken, invalidateLocalToken, tokenPath, DEFAULT_TOKEN_PATH };
