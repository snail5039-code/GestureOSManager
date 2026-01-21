import { useMemo, useState } from "react";
import { useAuth } from "../auth/AuthProvider";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function initials(name) {
  const s = String(name || "").trim();
  if (!s) return "U";
  const parts = s.split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase()).join("");
}

function ModalShell({ open, onClose, children }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center p-6">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-md">{children}</div>
    </div>
  );
}

export default function ProfileCard({ t, theme }) {
  const { user, isAuthed, booting, loginWithCredentials, logout } = useAuth();

  const [loginOpen, setLoginOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);

  const [loginId, setLoginId] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const [toast, setToast] = useState(null);

  const isBright = theme === "light" || theme === "rose";
  const shadow = isBright
    ? "shadow-[0_10px_30px_rgba(15,23,42,0.08)]"
    : "shadow-[0_12px_40px_rgba(0,0,0,0.25)]";

  const webBase = useMemo(
    () => import.meta.env.VITE_ACCOUNT_WEB_BASE || "http://localhost:5174",
    []
  );

  const openExternal = (url) => {
    if (window.managerWin?.openExternal) return window.managerWin.openExternal(url);
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const showToast = (msg) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 1400);
  };

  const onSubmitLogin = async (e) => {
    e.preventDefault();
    setErr("");

    const i = loginId.trim();
    const p = loginPw.trim();
    if (!i || !p) {
      setErr("아이디/비밀번호를 입력하세요.");
      return;
    }

    try {
      setBusy(true);
      await loginWithCredentials(i, p);
      setLoginOpen(false);
      setLoginPw("");
      showToast("로그인 완료");
    } catch (e2) {
      const msg =
        e2?.response?.status === 401
          ? "로그인 실패(아이디/비밀번호 확인)"
          : "로그인 실패(서버 확인)";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  const onConfirmLogout = async () => {
    try {
      setBusy(true);
      await logout();
      setLogoutOpen(false);
      showToast("로그아웃 완료");
    } finally {
      setBusy(false);
    }
  };

  const displayName = user?.nickname || user?.name || "User";

  return (
    <>
      <div className={cn("rounded-2xl ring-1 overflow-hidden", t.panel, shadow)}>
        <div className="h-px w-full bg-gradient-to-r from-sky-400/18 via-transparent to-transparent" />

        {/* Header */}
        <div
          className={cn(
            "flex items-center justify-between px-5 py-4 border-b",
            isBright ? "border-slate-200" : "border-white/10"
          )}
        >
          <div className={cn("text-sm font-semibold", t.text)}>프로필</div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              className={cn("px-3 py-1.5 text-xs rounded-full ring-1 transition", t.btn)}
              onClick={() => openExternal(`${webBase}/mypage`)}
            >
              웹페이지
            </button>

            {isAuthed ? (
              <button
                type="button"
                className={cn("px-3 py-1.5 text-xs rounded-full ring-1 transition", t.btn)}
                onClick={() => setLogoutOpen(true)}
              >
                로그아웃
              </button>
            ) : null}
          </div>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          {booting ? (
            <div className={cn("text-sm", t.muted)}>불러오는 중...</div>
          ) : isAuthed ? (
            <div className="flex items-center gap-4">
              <div className={cn("h-11 w-11 rounded-2xl ring-1 grid place-items-center", t.chip)}>
                <div className={cn("text-sm font-bold", t.text)}>{initials(displayName)}</div>
              </div>

              <div className="min-w-0 flex-1">
                <div className={cn("text-sm font-semibold truncate", t.text)}>{displayName}</div>
                <div className={cn("text-xs truncate mt-0.5", t.muted)}>{user?.email || "-"}</div>

                <div className="mt-2">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] ring-1 opacity-90",
                      t.chip,
                      t.muted
                    )}
                  >
                    {user?.role || "-"}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className={cn("text-sm", t.muted)}>
                계정 로그인 후 프로필과 동기화됩니다.
              </div>

              <button
                type="button"
                className={cn(
                  "w-full rounded-2xl py-3 text-sm font-semibold ring-1 transition active:scale-[0.99] flex items-center justify-center gap-2",
                  t.btn
                )}
                onClick={() => setLoginOpen(true)}
              >
                <span className="inline-block h-2 w-2 rounded-full bg-sky-400/80" />
                로그인
              </button>
            </div>
          )}
        </div>

        {/* Login Modal */}
        <ModalShell open={loginOpen} onClose={() => !busy && setLoginOpen(false)}>
          <div className={cn("rounded-2xl ring-1 overflow-hidden", t.panel, shadow)}>
            <div className="h-px w-full bg-gradient-to-r from-sky-400/25 via-transparent to-transparent" />
            <div
              className={cn(
                "px-5 py-4 border-b flex items-center justify-between",
                isBright ? "border-slate-200" : "border-white/10"
              )}
            >
              <div className={cn("text-sm font-semibold", t.text)}>로그인</div>
              <button
                type="button"
                className={cn("px-2 py-1 text-xs rounded-full ring-1 transition", t.btn)}
                onClick={() => !busy && setLoginOpen(false)}
              >
                닫기
              </button>
            </div>

            <form className="px-5 py-4 space-y-3" onSubmit={onSubmitLogin}>
              <input
                className={cn(
                  "w-full rounded-xl ring-1 px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50",
                  t.input,
                  isBright ? "focus:ring-sky-400/40" : "focus:ring-sky-500/45"
                )}
                placeholder="아이디"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                disabled={busy}
                autoFocus
              />

              <input
                className={cn(
                  "w-full rounded-xl ring-1 px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50",
                  t.input,
                  isBright ? "focus:ring-sky-400/40" : "focus:ring-sky-500/45"
                )}
                placeholder="비밀번호"
                type="password"
                value={loginPw}
                onChange={(e) => setLoginPw(e.target.value)}
                disabled={busy}
              />

              {err ? (
                <div className={cn("text-xs", isBright ? "text-rose-600" : "text-rose-200")}>
                  {err}
                </div>
              ) : null}

              <button
                type="submit"
                disabled={busy}
                className={cn(
                  "w-full rounded-2xl py-3 text-sm font-semibold ring-1 transition disabled:opacity-50",
                  t.btn
                )}
              >
                {busy ? "로그인 중..." : "로그인"}
              </button>
            </form>
          </div>
        </ModalShell>

        {/* Logout Confirm Modal */}
        <ModalShell open={logoutOpen} onClose={() => !busy && setLogoutOpen(false)}>
          <div className={cn("rounded-2xl ring-1 overflow-hidden", t.panel, shadow)}>
            <div className="h-px w-full bg-gradient-to-r from-rose-400/25 via-transparent to-transparent" />
            <div
              className={cn(
                "px-5 py-4 border-b flex items-center justify-between",
                isBright ? "border-slate-200" : "border-white/10"
              )}
            >
              <div className={cn("text-sm font-semibold", t.text)}>로그아웃</div>
              <button
                type="button"
                className={cn("px-2 py-1 text-xs rounded-full ring-1 transition", t.btn)}
                onClick={() => !busy && setLogoutOpen(false)}
              >
                닫기
              </button>
            </div>

            <div className="px-5 py-4 space-y-3">
              <div className={cn("text-sm", t.text)}>정말 로그아웃할까요?</div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={cn(
                    "flex-1 rounded-2xl py-3 text-sm font-semibold ring-1 transition",
                    t.btn
                  )}
                  onClick={() => !busy && setLogoutOpen(false)}
                  disabled={busy}
                >
                  취소
                </button>
                <button
                  type="button"
                  className={cn(
                    "flex-1 rounded-2xl py-3 text-sm font-semibold ring-1 transition",
                    t.btn
                  )}
                  onClick={onConfirmLogout}
                  disabled={busy}
                >
                  {busy ? "처리 중..." : "로그아웃"}
                </button>
              </div>
            </div>
          </div>
        </ModalShell>
      </div>

      {/* Toast */}
      {toast ? (
        <div className="fixed bottom-6 left-6 z-[1000]">
          <div className={cn("px-4 py-2 rounded-2xl ring-1 text-sm", t.panel, t.text, shadow)}>
            {toast}
          </div>
        </div>
      ) : null}
    </>
  );
}
