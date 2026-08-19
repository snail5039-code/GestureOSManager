import { useMemo } from "react";
import { useAuth } from "./AuthProvider";

/**
 * 서버로 보낼 회원 ID 와 헤더를 만든다.
 *
 * 서버(TrainingController)는 X-User-Id 를 숫자로만 파싱하고, 숫자가 아니면 게스트로
 * 처리한다. 그런데 화면마다 이 값을 다르게 만들고 있었다.
 *
 *   Dashboard, ProfileCard : /^\d+$/ 로 걸러 숫자만 보냄 (정상)
 *   TrainingLab            : user.email 까지 폴백해서 보냄 -> 서버가 게스트로 강등
 *
 * 그래서 TrainingLab 에서만 "로그인했는데 프로필 생성이 LOGIN_REQUIRED 로 거절"되는
 * 일이 생겼다. 판단을 한 곳으로 모아서 세 화면이 같은 규칙을 쓰게 한다.
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

  const userHeaders = useMemo(
    () => (isGuest ? {} : { "X-User-Id": memberId }),
    [isGuest, memberId],
  );

  return { memberId, isGuest, userHeaders };
}

export default useMemberId;
