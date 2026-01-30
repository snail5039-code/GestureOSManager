import axios from "axios";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthProvider";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function ModalShell({ open, onClose, children }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[999] flex items-center justify-center p-6">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-[2px]" onMouseDown={onClose} />
      <div className="relative w-full max-w-md">{children}</div>
    </div>
  );
}

function IconRefresh({ spinning }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className={cn("opacity-90", spinning && "animate-spin")}>
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
  // ✅ dev(vite)에서는 proxy(/api), 설치본(file://)에서는 Web(Spring:8082)
  baseURL:
    typeof window !== "undefined" && window.location.protocol === "file:"
      ? "http://127.0.0.1:8080/api"
      : "/api",
  timeout: 5000,
  headers: { Accept: "application/json" },
});

export default function ProfileCard({ t, theme, onOpenTraining }) {
  const { user, isAuthed, booting, loginWithCredentials, logout, refreshMe, profileBump } = useAuth();
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

  // ===== profile switch
  // ✅ X-User-Id는 서버에서 Long으로 파싱됨 → 숫자만 허용
  const memberId = useMemo(() => {
    const raw = user?.id ?? user?.memberId ?? user?.member_id ?? null;
    if (raw === null || raw === undefined) return null;
    const s = String(raw).trim();
    if (!/^\d+$/.test(s)) return null;
    return s;
  }, [user]);

  const memberKey = useMemo(() => {
    const raw = memberId ? String(memberId) : "guest";
    return raw.replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase();
  }, [memberId]);

  const isGuest = !isAuthed || !memberId;

  const userHeaders = useMemo(() => {
    if (isGuest) return {};
    return { "X-User-Id": memberId };
  }, [isGuest, memberId]);

  const NS = useMemo(() => (isGuest ? "" : `u${memberKey}__`), [isGuest, memberKey]);

  const displayProfile = useCallback(
    (p) => {
      const s = String(p || "");
      if (s === "default") return "기본";
      if (!NS) return s;
      return s.startsWith(NS) ? s.slice(NS.length) : s;
    },
    [NS],
  );

  const [learnProfile, setLearnProfile] = useState("default");
  const [learnProfiles, setLearnProfiles] = useState([]);
  const [dbProfiles, setDbProfiles] = useState([]);
  const [profileBusy, setProfileBusy] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileSel, setProfileSel] = useState("default");

  const fetchProfiles = useCallback(async () => {
    setProfileError("");
    setProfileBusy(true);
    try {
      const { data } = await api.get("/train/stats", { headers: userHeaders });
      const p = data?.learnProfile || "default";
      const ps = Array.isArray(data?.learnProfiles) ? data.learnProfiles : [];
      setLearnProfile(p);
      setLearnProfiles(ps);
      setProfileSel((cur) => (profileBusy ? cur : p));

      if (!isGuest) {
        try {
          const r = await api.get("/train/profile/db/list", { headers: userHeaders });
          setDbProfiles(Array.isArray(r?.data?.profiles) ? r.data.profiles : []);
        } catch {
          setDbProfiles([]);
        }
      } else {
        setDbProfiles([]);
      }
    } catch (e) {
      const msg = e?.response ? `프로필 조회 실패 (HTTP ${e.response.status})` : e?.message || "프로필 조회 실패";
      setProfileError(msg);
    } finally {
      setProfileBusy(false);
    }
  }, [isGuest, userHeaders, profileBusy]);

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

  // ✅ 수정 포인트: 내 프로필(NS) + 공용(NS 없음) 둘 다 노출
  const profileOptions = useMemo(() => {
    if (isGuest) return [{ value: "default", label: "default(기본)" }];

    const set = new Set(["default", learnProfile, ...(learnProfiles || []), ...(dbProfiles || [])]);
    const all = Array.from(set).filter(Boolean);

    const mineRaw = all.filter((p) => p === "default" || String(p).startsWith(NS));
    const sharedRaw = all.filter((p) => p !== "default" && !String(p).startsWith(NS));

    const mine = mineRaw
      .map((p) => ({ value: p, label: displayProfile(p) }))
      .sort((a, b) => (a.value === "default" ? -1 : b.value === "default" ? 1 : a.label.localeCompare(b.label)));

    const shared = sharedRaw
      .map((p) => ({ value: p, label: `공용 · ${p}` }))
      .sort((a, b) => a.label.localeCompare(b.label));

    const sep = shared.length > 0 ? [{ value: "__sep_shared__", label: "──────── 공용 프로필 ────────", disabled: true }] : [];

    return [...mine, ...sep, ...shared];
  }, [NS, dbProfiles, displayProfile, isGuest, learnProfile, learnProfiles]);

  const setServerProfile = useCallback(
    async (name) => {
      const target = isGuest ? "default" : name;
      if (isGuest && target !== "default") {
        showToast("게스트: default만 가능");
        setProfileSel("default");
        setLearnProfile("default");
        return;
      }

      // ✅ 낙관적 반영: UI는 즉시 바뀐 것처럼 보여줌
      setLearnProfile(target);
      setProfileSel(target);

      setProfileBusy(true);
      setProfileError("");

      try {
        const { data } = await api.post("/train/profile/set", null, {
          params: { name: target },
          headers: userHeaders,
        });

        if (!data?.ok) {
          showToast("프로필 적용 실패");
          // 실패 시 서버값으로 되돌림
          await fetchProfiles();
          return;
        }

        showToast(`프로필 적용: ${displayProfile(target)}`);

        // ✅ stats가 늦게 따라오므로 짧게 폴링해서 "진짜 반영"을 기다림
        const deadline = Date.now() + 1500; // 1.5초만
        while (Date.now() < deadline) {
          try {
            const r = await api.get("/train/stats", { headers: userHeaders });
            const p = r?.data?.learnProfile || "default";
            setLearnProfile(p);

            // 서버가 target으로 바뀌면 종료
            if (p === target) break;
          } catch {
            // ignore
          }
          await new Promise((res) => setTimeout(res, 120));
        }

        // 마지막으로 목록 동기화(learnProfiles/dbProfiles 갱신)
        await fetchProfiles();
      } catch (e) {
        const msg = e?.response ? `프로필 적용 실패 (HTTP ${e.response.status})` : e?.message || "프로필 적용 실패";
        setProfileError(msg);
        showToast("프로필 적용 실패");
        // 서버값으로 복구
        await fetchProfiles();
      } finally {
        setProfileBusy(false);
      }
    },
    [displayProfile, fetchProfiles, isGuest, userHeaders, showToast],
  );


  const isBright = theme === "light" || theme === "rose";

  const webBase = useMemo(() => import.meta.env.VITE_ACCOUNT_WEB_BASE || "http://localhost:5174", []);
  const openExternal = (url) => {
    if (window.managerWin?.openExternal) return window.managerWin.openExternal(url);
    window.open(url, "_blank", "noopener,noreferrer");
  };

  useEffect(() => {
    if (!isAuthed || typeof refreshMe !== "function") return;

    const onFocus = () => refreshMe().catch(() => { });
    const onVis = () => {
      if (!document.hidden) refreshMe().catch(() => { });
    };

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVis);

    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [isAuthed, refreshMe]);

  const onSubmitLogin = async (e) => {
    e.preventDefault();
    setErr("");
    const i = loginId.trim();
    const p = loginPw.trim();
    if (!i || !p) return setErr("아이디/비밀번호를 입력하세요.");

    try {
      setBusy(true);
      await loginWithCredentials(i, p);
      setLoginOpen(false);
      setLoginPw("");
      showToast("로그인 완료");
    } catch (e2) {
      setErr(e2?.response?.status === 401 ? "로그인 실패(아이디/비밀번호 확인)" : "로그인 실패(서버 확인)");
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
  const email = user?.email || "-";
  const role = user?.role || "-";

  // ===== ONLY FIXED PART =====
  const profileImgUrl = useMemo(() => {
    const rawPath =
      user?.profileImageUrl ||
      user?.profile_image_url ||
      user?.profileImage ||
      user?.profile_image ||
      user?.image ||
      user?.avatar;

    if (!rawPath) return null;
    if (/^https?:\/\//i.test(rawPath)) return rawPath;

    const cleanPath = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
    return `${webBase}${cleanPath}`;
  }, [user, webBase]);
  // ===========================

  const frame = cn("rounded-lg ring-1 overflow-hidden", t.panel);
  const header = cn("px-4 py-3 border-b flex items-center justify-between", isBright ? "border-slate-200" : "border-white/10");
  const body = "px-4 py-3";
  const subtleBtn = cn("text-xs font-semibold underline underline-offset-4 opacity-90 hover:opacity-100 transition", t.text2);

  return (
    <>
      <div className={frame}>
        <div className={header}>
          <div className={cn("text-sm font-semibold tracking-tight", t.text)}>프로필</div>
          <div className="flex items-center gap-3">
            <button type="button" className={subtleBtn} onClick={() => openExternal(`${webBase}/mypage`)}>
              웹페이지
            </button>
            {isAuthed ? (
              <button type="button" className={subtleBtn} onClick={() => setLogoutOpen(true)}>
                로그아웃
              </button>
            ) : null}
          </div>
        </div>

        <div className={body}>
          {booting ? (
            <div className={cn("text-sm", t.muted)}>불러오는 중...</div>
          ) : isAuthed ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className={cn("text-[15px] font-semibold truncate", t.text)}>{displayName}</div>
                    <span
                      className={cn(
                        "inline-flex items-center px-2 py-0.5 text-[11px] ring-1 rounded-sm",
                        isBright ? "bg-slate-100 ring-slate-200 text-slate-900" : "bg-white/10 ring-white/12 text-white/90",
                      )}
                    >
                      {role}
                    </span>
                  </div>
                  <div className={cn("text-xs mt-1 truncate", t.muted)}>{email}</div>
                </div>

                <div
                  className={cn(
                    "h-8 w-8 rounded-md ring-1 grid place-items-center text-[12px] font-bold overflow-hidden shrink-0",
                    isBright ? "bg-white ring-slate-200" : "bg-white/5 ring-white/12",
                    t.text,
                  )}
                  title="계정"
                >
                  {profileImgUrl ? (
                    <img
                      src={profileImgUrl}
                      alt=""
                      className="h-full w-full object-cover"
                      onError={(e) => {
                        e.target.style.display = "none";
                        e.target.parentElement.innerText = /[^\x00-\x7F]/.test(displayName)
                          ? displayName.slice(0, 1)
                          : displayName.slice(0, 2).toUpperCase();
                      }}
                    />
                  ) : /[^\x00-\x7F]/.test(displayName) ? (
                    displayName.slice(0, 1)
                  ) : (
                    displayName.slice(0, 2).toUpperCase()
                  )}
                </div>
              </div>

              <div className={cn("rounded-md ring-1 p-3", t.panelSoft, isBright ? "ring-slate-200" : "ring-white/12")}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className={cn("text-xs font-semibold", t.text)}>나의 제스처 설정</div>
                    <div className={cn("mt-1 text-[11px] truncate", t.muted)}>
                      현재: <span className={cn("font-semibold", t.text2)}>{displayProfile(learnProfile)}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      className={cn("h-8 w-8 grid place-items-center rounded-md ring-1 transition", t.btn)}
                      onClick={() => !profileBusy && fetchProfiles()}
                      disabled={profileBusy}
                      title="새로고침"
                    >
                      <IconRefresh spinning={profileBusy} />
                    </button>

                    {typeof onOpenTraining === "function" ? (
                      <button
                        type="button"
                        className={cn("h-8 px-3 text-xs font-semibold rounded-md ring-1 transition", t.btn)}
                        onClick={onOpenTraining}
                        disabled={profileBusy}
                      >
                        트레이닝
                      </button>
                    ) : null}
                  </div>
                </div>

                <select
                  value={profileSel}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === "__sep_shared__") return; // ✅ 구분선 선택 방지
                    setProfileSel(v);
                    setServerProfile(v);
                  }}
                  disabled={profileBusy}
                  className={cn(
                    "mt-2 w-full rounded-md ring-1 px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50",
                    t.input,
                    isBright ? "focus:ring-sky-400/40" : "focus:ring-sky-500/45",
                  )}
                >
                  {profileOptions.map((p) => (
                    <option key={p.value} value={p.value} disabled={!!p.disabled}>
                      {p.label}
                    </option>
                  ))}
                </select>

                {profileError ? (
                  <div className={cn("mt-2 text-[11px]", isBright ? "text-rose-600" : "text-rose-200")}>{profileError}</div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className={cn("text-sm", t.muted)}>계정 로그인 후 프로필과 동기화됩니다.</div>
              <button
                type="button"
                className={cn("w-full rounded-md py-3 text-sm font-semibold ring-1 transition active:scale-[0.99]", t.btn)}
                onClick={() => setLoginOpen(true)}
              >
                로그인
              </button>
            </div>
          )}
        </div>

        <ModalShell open={loginOpen} onClose={() => !busy && setLoginOpen(false)}>
          <div className={cn("rounded-md ring-1 overflow-hidden", t.panel)}>
            <div className={cn("px-4 py-3 border-b flex items-center justify-between", isBright ? "border-slate-200" : "border-white/10")}>
              <div className={cn("text-sm font-semibold", t.text)}>로그인</div>
              <button
                type="button"
                className={cn("px-2.5 py-1.5 text-xs rounded-md ring-1 transition", t.btn)}
                onClick={() => !busy && setLoginOpen(false)}
              >
                닫기
              </button>
            </div>

            <form className="px-4 py-4 space-y-3" onSubmit={onSubmitLogin}>
              <input
                className={cn("w-full rounded-md ring-1 px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50", t.input)}
                placeholder="아이디"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                disabled={busy}
                autoFocus
              />
              <input
                className={cn("w-full rounded-md ring-1 px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50", t.input)}
                placeholder="비밀번호"
                type="password"
                value={loginPw}
                onChange={(e) => setLoginPw(e.target.value)}
                disabled={busy}
              />
              {err ? <div className={cn("text-xs", isBright ? "text-rose-600" : "text-rose-200")}>{err}</div> : null}
              <button
                type="submit"
                disabled={busy}
                className={cn("w-full rounded-md py-3 text-sm font-semibold ring-1 transition disabled:opacity-50", t.btn)}
              >
                {busy ? "로그인 중..." : "로그인"}
              </button>
            </form>
          </div>
        </ModalShell>

        <ModalShell open={logoutOpen} onClose={() => !busy && setLogoutOpen(false)}>
          <div className={cn("rounded-md ring-1 overflow-hidden", t.panel)}>
            <div className={cn("px-4 py-3 border-b flex items-center justify-between", isBright ? "border-slate-200" : "border-white/10")}>
              <div className={cn("text-sm font-semibold", t.text)}>로그아웃</div>
              <button
                type="button"
                className={cn("px-2.5 py-1.5 text-xs rounded-md ring-1 transition", t.btn)}
                onClick={() => !busy && setLogoutOpen(false)}
              >
                닫기
              </button>
            </div>

            <div className="px-4 py-4 space-y-3">
              <div className={cn("text-sm", t.text)}>정말 로그아웃할까요?</div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={cn("flex-1 rounded-md py-3 text-sm font-semibold ring-1 transition", t.btn)}
                  onClick={() => !busy && setLogoutOpen(false)}
                  disabled={busy}
                >
                  취소
                </button>
                <button
                  type="button"
                  className={cn("flex-1 rounded-md py-3 text-sm font-semibold ring-1 transition", t.btn)}
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

      {toast ? (
        <div className="fixed bottom-6 left-6 z-[1000]">
          <div className={cn("px-4 py-2 rounded-md ring-1 text-sm", t.panel, t.text)}>{toast}</div>
        </div>
      ) : null}
    </>
  );
}
