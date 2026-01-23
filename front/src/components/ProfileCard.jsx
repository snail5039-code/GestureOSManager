import axios from "axios";
import { useCallback, useEffect, useMemo, useState } from "react";
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

function IconRefresh({ spinning }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      className={cn("opacity-90", spinning && "animate-spin")}
    >
      <path
        d="M20 12a8 8 0 1 1-2.34-5.66M20 4v6h-6"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const api = axios.create({
  baseURL: "/api",
  timeout: 5000,
  headers: { Accept: "application/json" },
});

export default function ProfileCard({ t, theme, onOpenTraining }) {
  const { user, isAuthed, booting, loginWithCredentials, logout } = useAuth();

  const [loginOpen, setLoginOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);

  const [loginId, setLoginId] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const [toast, setToast] = useState(null);

  const showToast = useCallback((msg) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 1400);
  }, []);

  // =========================
  // ✅ Custom profile quick switch (TrainingLab profiles)
  // =========================
  const memberIdRaw =
    user?.id ?? user?.memberId ?? user?.member_id ?? user?.email ?? null;

  const memberKey = useMemo(() => {
    const raw = memberIdRaw ? String(memberIdRaw) : "guest";
    return raw.replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase();
  }, [memberIdRaw]);

  const isGuest = !isAuthed || !memberIdRaw;

  const userHeaders = useMemo(() => {
    if (isGuest) return {};
    return { "X-User-Id": String(memberIdRaw) };
  }, [isGuest, memberIdRaw]);

  const NS = useMemo(() => (isGuest ? "" : `u${memberKey}__`), [isGuest, memberKey]);

  const displayProfile = useCallback(
    (p) => {
      const s = String(p || "");
      if (s === "default") return "default(기본)";
      if (!NS) return s;
      return s.startsWith(NS) ? s.slice(NS.length) : s;
    },
    [NS]
  );

  const [learnProfile, setLearnProfile] = useState("default");
  const [learnProfiles, setLearnProfiles] = useState([]);
  const [dbProfiles, setDbProfiles] = useState([]);
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileSel, setProfileSel] = useState("default");

  const fetchProfiles = useCallback(async () => {
    setProfileError("");
    try {
      // 현재 적용 프로필 / 서버가 기억하는 profile list
      const { data } = await api.get("/train/stats", { headers: userHeaders });
      const p = data?.learnProfile || "default";
      const ps = Array.isArray(data?.learnProfiles) ? data.learnProfiles : [];
      setLearnProfile(p);
      setLearnProfiles(ps);
      setProfileSel(p);

      // DB profile list
      if (!isGuest) {
        const r = await api.get("/train/profile/db/list", { headers: userHeaders });
        setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
      } else {
        setDbProfiles([]);
      }
    } catch (e) {
      const msg = e?.response
        ? `프로필 조회 실패 (HTTP ${e.response.status})`
        : e?.message || "프로필 조회 실패";
      setProfileError(msg);
    }
  }, [isGuest, userHeaders]);

  useEffect(() => {
    if (!isAuthed) {
      setLearnProfile("default");
      setLearnProfiles([]);
      setDbProfiles([]);
      setProfileSel("default");
      setProfileError("");
      setProfileBusy(false);
      return;
    }
    fetchProfiles();
  }, [isAuthed, fetchProfiles]);

  const profileOptions = useMemo(() => {
    if (isGuest) return [{ value: "default", label: "default(기본)" }];

    const set = new Set(["default", learnProfile, ...(learnProfiles || []), ...(dbProfiles || [])]);
    const all = Array.from(set).filter(Boolean);

    const mine = all
      .filter((p) => p === "default" || String(p).startsWith(NS))
      .map((p) => ({ value: p, label: displayProfile(p) }));

    if (learnProfile && learnProfile !== "default" && !mine.some((x) => x.value === learnProfile)) {
      mine.push({ value: learnProfile, label: displayProfile(learnProfile) });
    }

    const base = mine.filter((x) => x.value === "default");
    const rest = mine
      .filter((x) => x.value !== "default")
      .sort((a, b) => a.label.localeCompare(b.label));

    return [...base, ...rest];
  }, [NS, dbProfiles, displayProfile, isGuest, learnProfile, learnProfiles]);

  const setServerProfile = useCallback(
    async (name) => {
      const target = isGuest ? "default" : name;
      if (isGuest && target !== "default") {
        showToast("게스트: default만 가능");
        setProfileSel("default");
        return;
      }

      setProfileBusy(true);
      setProfileError("");
      try {
        const { data } = await api.post("/train/profile/set", null, {
          params: { name: target },
          headers: userHeaders,
        });
        if (data?.ok) showToast(`프로필 적용: ${displayProfile(target)}`);
        else showToast("프로필 적용 실패");
        await fetchProfiles();
      } catch (e) {
        const msg = e?.response
          ? `프로필 적용 실패 (HTTP ${e.response.status})`
          : e?.message || "프로필 적용 실패";
        setProfileError(msg);
        showToast("프로필 적용 실패");
      } finally {
        setProfileBusy(false);
      }
    },
    [displayProfile, fetchProfiles, isGuest, userHeaders, showToast]
  );

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
            <div className="flex items-stretch gap-4">
              {/* left: user info */}
              <div className="flex items-center gap-4 min-w-0 flex-1">
                <div className={cn("h-11 w-11 rounded-2xl ring-1 grid place-items-center", t.chip)}>
                  <div className={cn("text-sm font-bold", t.text)}>{initials(displayName)}</div>
                </div>

                <div className="min-w-0">
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

              {/* right: profile quick switch */}
              <div className="w-[240px] shrink-0">
                <div className={cn("rounded-2xl ring-1 p-3", t.panelSoft)}>
                  <div className="flex items-center justify-between">
                    <div className={cn("text-xs font-semibold", t.text)}>커스텀 프로필</div>

                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        className={cn(
                          "h-7 w-7 grid place-items-center rounded-xl ring-1 transition",
                          t.btn
                        )}
                        onClick={() => !profileBusy && fetchProfiles()}
                        disabled={profileBusy}
                        title="새로고침"
                      >
                        <IconRefresh spinning={profileBusy} />
                      </button>

                      {typeof onOpenTraining === "function" ? (
                        <button
                          type="button"
                          className={cn(
                            "h-7 px-2.5 text-[11px] font-semibold rounded-xl ring-1 transition",
                            t.btn
                          )}
                          onClick={onOpenTraining}
                          disabled={profileBusy}
                          title="트레이닝 랩 열기"
                        >
                          트레이닝
                        </button>
                      ) : null}
                    </div>
                  </div>

                  <div className={cn("mt-1 text-[11px]", t.muted)}>
                    현재:{" "}
                    <span className={cn("font-semibold", t.text2)}>
                      {displayProfile(learnProfile)}
                    </span>
                  </div>

                  <select
                    value={profileSel}
                    onChange={(e) => {
                      const v = e.target.value;
                      setProfileSel(v);
                      setServerProfile(v);
                    }}
                    disabled={profileBusy}
                    className={cn(
                      "mt-2 w-full rounded-xl ring-1 px-3 py-1.5 text-sm outline-none focus:ring-2 disabled:opacity-50",
                      t.input,
                      isBright ? "focus:ring-sky-400/40" : "focus:ring-sky-500/45"
                    )}
                  >
                    {profileOptions.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>

                  {profileError ? (
                    <div className={cn("mt-2 text-[11px]", isBright ? "text-rose-600" : "text-rose-200")}>
                      {profileError}
                    </div>
                  ) : null}

                  <div className={cn("mt-2 text-[11px]", t.muted)}>
                    커스텀한 프로필을 적용시켜보세요
                  </div>
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
