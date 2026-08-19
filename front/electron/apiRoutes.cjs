// 패키징 실행에서 메인 프로세스가 /api 요청을 어디로 중계할지 정하는 규칙.
//
// 개발 중에는 vite.config.js 의 proxy 가 같은 일을 한다. 두 곳의 규칙이 어긋나면
// "개발에서는 되는데 설치본에서는 안 되는" 버그가 생기므로, 판단 부분만 떼어내
// electron 의존 없이 테스트할 수 있게 했다.
//
//   /api/auth/**    -> 계정 서버 (Spring 8082)
//   /api/members/** -> 계정 서버 (Spring 8082)
//   /api/**         -> 에이전트 서버 (Spring 8080)
//   /motion/**      -> 에이전트 서버 (Spring 8080)
//   그 외           -> null (dist 의 정적 파일)

const path = require("node:path");

const ACCOUNT_PATHS = /^\/api\/(auth|members)(\/|$)/;
const AGENT_PATHS = /^\/(api|motion)(\/|$)/;

/**
 * @param {string} pathname URL 의 pathname (쿼리 제외)
 * @param {{agent: string, account: string}} origins
 * @returns {string|null} 중계할 오리진, 중계 대상이 아니면 null
 */
function resolveApiTarget(pathname, origins) {
  if (typeof pathname !== "string" || !pathname.startsWith("/")) return null;
  if (ACCOUNT_PATHS.test(pathname)) return origins.account;
  if (AGENT_PATHS.test(pathname)) return origins.agent;
  return null;
}

/**
 * 앱 스킴 요청을 dist 안의 실제 파일 경로로 바꾼다.
 * dist 밖을 가리키는 요청(인코딩된 상위 경로 포함)은 null 을 준다.
 *
 * @param {string} pathname URL 의 pathname
 * @param {string} distDir 빌드 결과 폴더(절대 경로)
 * @returns {string|null}
 */
function resolveDistPath(pathname, distDir) {
  let rel;
  try {
    rel = decodeURIComponent(pathname || "/");
  } catch {
    return null; // 잘못된 퍼센트 인코딩
  }

  if (!rel || rel === "/") rel = "/index.html";
  if (rel.includes("\0")) return null;

  const full = path.normalize(path.join(distDir, rel));

  if (full !== distDir && !full.startsWith(distDir + path.sep)) return null;
  return full;
}

module.exports = { resolveApiTarget, resolveDistPath };
