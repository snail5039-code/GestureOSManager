import { useMemo } from "react";
import { useAuth } from "./AuthProvider";
import { getStoredAccessToken } from "../api/accountClient";

/**
 * 회원 식별에 필요한 값들을 한 곳에서 만든다.
 *
 * - memberId: 로컬 이름 규칙(프로필 네임스페이스, 데이터셋 키)에만 쓴다.
 *   화면마다 계산이 달랐고(TrainingLab 만 user.email 폴백), 그 때문에 로그인했는데도
 *   서버가 게스트로 처리하는 일이 있었다.
 * - authHeaders: 서버에 보낼 인증 헤더.
 *   예전에는 X-User-Id 에 숫자를 담아 보냈고 서버가 그걸 그대로 믿었다. 헤더만 바꾸면
 *   남의 학습 프로필을 읽고 지울 수 있었기 때문에, 이제 액세스 토큰을 보내고 서버가
 *   계정 서버에 확인해서 신원을 정한다.
 *
 * @returns {{memberId: string|null, isGuest: boolean, userHeaders: object}}
 */
export function useMemberId() {
  const { user, isAuthed } = useAuth();

  const memberId = useMemo(() => {
    const raw = user?.id ?? user?.memberId ?? user?.member_id ?? null;
    if (raw === null || raw === undefined) return null;

    const s = String(raw).trim();
    // 이메일 등 숫자가 아닌 값은 보내지 않는다(서버가 게스트로 처리하므로 무의미).
    if (!/^\d+$/.test(s)) return null;

    return s;
  }, [user]);

  const isGuest = !isAuthed || !memberId;

  // 토큰은 매 렌더가 아니라 요청 시점 값이 중요하므로 여기서 읽어 헤더로 만든다.
  // (accountApi 인스턴스는 인터셉터가 알아서 붙이지만, 매니저 서버로 가는 요청은
  //  이 헤더를 직접 실어 보내야 한다)
  const userHeaders = useMemo(() => {
    if (isGuest) return {};
    const token = getStoredAccessToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [isGuest, memberId]);

  return { memberId, isGuest, userHeaders };
}

export default useMemberId;
