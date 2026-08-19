import { useEffect, useMemo, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage";
import PairingQrModal from "./components/PairingQrModal";
import TrainingLab from "./pages/TrainingLab";
import { THEME } from "./theme/themeTokens";
import { setStoredAccessToken } from "./api/accountClient";
import { useAuth } from "./auth/AuthProvider";

const VALID_THEMES = new Set(["dark", "light", "neon", "rose", "devil"]);

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

export default function App() {
  const { refreshMe } = useAuth();

  const [hudOn, setHudOn] = useState(() => {
    const v = localStorage.getItem("hudOn");
    return v === null ? true : v === "1";
  });

  const [osHudOn, setOsHudOn] = useState(() => {
    const v = localStorage.getItem("osHudOn");
    return v === null ? true : v === "1";
  });

  useEffect(() => {
    if (!window.managerWin?.onDeepLink) return;

    const off = window.managerWin.onDeepLink(async (rawUrl) => {
      try {
        let code = null;

        try {
          const u = new URL(rawUrl);
          code = u.searchParams.get("code");
        } catch {
          const qs = rawUrl.split("?")[1] || "";
          code = new URLSearchParams(qs).get("code");
        }

        if (!code) return;

        const res = await fetch("/api/auth/bridge/consume", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          credentials: "include",
          body: JSON.stringify({ code }),
        });

        if (!res.ok) throw new Error(`consume failed: ${res.status}`);

        const data = await res.json();

        if (!data?.accessToken) throw new Error("no accessToken in consume response");

        // AuthProvider 가 읽는 것과 같은 키에 저장한다.
        // (예전에는 "accessToken" 에 넣고 reload 했는데, AuthProvider 는 다른 키를 봐서
        //  딥링크로 로그인해도 로그인 상태가 되지 않았다)
        setStoredAccessToken(data.accessToken);

        // 새로고침 대신 사용자 정보만 다시 읽는다.
        await refreshMe();
      } catch (e) {
        console.error("deeplink auth failed:", e);
      }
    });

    return off;
  }, [refreshMe]);

  useEffect(() => {
    localStorage.setItem("hudOn", hudOn ? "1" : "0");
  }, [hudOn]);

  useEffect(() => {
    localStorage.setItem("osHudOn", osHudOn ? "1" : "0");
    fetch(`/api/hud/show?enabled=${osHudOn ? "true" : "false"}`, {
      method: "POST",
    }).catch(() => {});
  }, [osHudOn]);

  const toggleHud = () => setHudOn((x) => !x);
  const toggleOsHud = () => setOsHudOn((x) => !x);

  const [screen, setScreen] = useState("dashboard");
  const [hudFeed, setHudFeed] = useState(null);
  const hudActionsRef = useRef({});

  const [pairOpen, setPairOpen] = useState(false);
  const [pairing, setPairing] = useState(() => ({
    pc: "",
    httpPort: 8081,
    udpPort: 39500,
    name: "PC",
  }));

  const refreshPairing = () => {
    let cancelled = false;

    fetch("/api/pairing")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        if (cancelled || !data) return;
        setPairing((prev) => ({ ...prev, ...data }));
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  };

  // 저장 실패를 삼키면 사용자는 값을 고쳐도 아무 일도 일어나지 않은 것처럼 보인다.
  // 실패는 호출한 쪽(페어링 모달)이 표시할 수 있게 그대로 올린다.
  const savePairing = async (patch) => {
    const res = await fetch("/api/pairing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });

    if (!res.ok) {
      let message = `저장 실패 (HTTP ${res.status})`;
      try {
        const body = await res.json();
        if (body?.message) message = String(body.message);
      } catch {
        // 본문이 JSON 이 아니면 기본 문구를 쓴다
        message = `저장 실패 (HTTP ${res.status})`;
      }
      throw new Error(message);
    }

    refreshPairing();
  };

  const savePairingName = (nextName) => {
    const name = String(nextName || "").trim() || "PC";
    return savePairing({ name });
  };

  const savePairingPc = (nextPc) => {
    const pc = String(nextPc || "").trim();
    if (!pc) return Promise.resolve();
    return savePairing({ pc });
  };

  useEffect(() => {
    const cleanup = refreshPairing();
    return cleanup;
  }, []);

  const [theme, _setTheme] = useState(() => {
    const saved = localStorage.getItem("theme") || "dark";
    return VALID_THEMES.has(saved) ? saved : "dark";
  });

  const setTheme = (next) => {
    const v = String(next || "").trim();
    if (!VALID_THEMES.has(v)) return;
    _setTheme(v);
  };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const t = THEME[theme] || THEME.dark;

  const agentStatus = useMemo(() => {
    return {
      connected: !!hudFeed?.connected,
      locked: !!hudFeed?.locked,
      mode: hudFeed?.mode ?? "DEFAULT",
      cameraPresent: hudFeed?.cameraPresent ?? null,
      modeText: hudFeed?.modeText ?? undefined,
    };
  }, [hudFeed]);

  return (
    <div
      data-theme={theme}
      className={cn(
        "w-[100dvw] h-[100dvh] flex flex-col overflow-hidden min-w-0 min-h-0 relative",
        t.page,
      )}
    >
      {/* background */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div
          className={cn(
            "absolute -top-40 -left-40 h-[520px] w-[520px] rounded-full blur-3xl",
            t.glow1,
          )}
        />
        <div
          className={cn(
            "absolute -bottom-52 -right-48 h-[560px] w-[560px] rounded-full blur-3xl",
            t.glow2,
          )}
        />
        <div className={cn("absolute inset-0 bg-[size:60px_60px]", t.grid)} />
      </div>

      {/* TitleBar */}
      <div className="relative z-30">
        <TitleBar
          hudOn={hudOn}
          onToggleHud={toggleHud}
          osHudOn={osHudOn}
          onToggleOsHud={toggleOsHud}
          screen={screen}
          onChangeScreen={setScreen}
          theme={theme}
          setTheme={setTheme}
          agentStatus={agentStatus}
          onOpenPairing={() => {
            refreshPairing();
            setPairOpen(true);
          }}
        />
      </div>

      {/*
        HUD 는 오른쪽 위에 고정된 340px 패널이다(AgentHud: fixed right-4 top-14).
        그래서 그 폭만큼 오른쪽을 비워주지 않으면 상태 카드의 오른쪽 열(잠금/스크롤/포인터 Y)이
        패널에 덮여 잘린다.

        예전에는 bottom padding(pb-28)만 있었다. HUD 가 화면 아래쪽 바였던 시절의 보정이
        그대로 남아 있어서, 위치가 오른쪽 위로 바뀐 뒤에는 엉뚱한 곳을 비우고 있었다.
      */}
      <main
        className={cn(
          "relative z-10 flex-1 min-h-0 min-w-0 text-sm",
          screen === "rush" ? "overflow-hidden" : "overflow-auto",
          screen !== "rush" ? (hudOn ? "pb-6 pr-[356px]" : "pb-6") : "",
        )}
      >
        <div className={cn(screen === "dashboard" ? "block" : "hidden", "w-full min-w-0")}>
          <Dashboard
            hudOn={hudOn}
            onToggleHud={toggleHud}
            onHudState={setHudFeed}
            onHudActions={(actions) => {
              hudActionsRef.current = actions || {};
            }}
            theme={theme}
            onChangeScreen={setScreen}
          />
        </div>

        {screen === "rush" && (
          <Rush3DPage status={hudFeed?.status} connected={hudFeed?.connected ?? true} />
        )}
        {screen === "settings" && <Settings theme={theme} />}
        {screen === "train" && <TrainingLab theme={theme} />}
      </main>

      {/* overlays */}
      <div className="relative z-40">
        {hudOn && (
          <AgentHud
            status={hudFeed?.status}
            connected={hudFeed?.connected ?? true}
            modeOptions={hudFeed?.modeOptions}
            onSetMode={(m) => hudActionsRef.current.applyMode?.(m)}
            onEnableToggle={(next) =>
              next ? hudActionsRef.current.start?.() : hudActionsRef.current.stop?.()
            }
            onPreviewToggle={() => hudActionsRef.current.togglePreview?.()}
            onLockToggle={(nextLocked) => {
              if (hudActionsRef.current.setLock) return hudActionsRef.current.setLock(nextLocked);
              return hudActionsRef.current.lockToggle?.();
            }}
            onRequestHide={() => setHudOn(false)}
          />
        )}

        <PairingQrModal
          open={pairOpen}
          onClose={() => setPairOpen(false)}
          pairing={pairing}
          onSaveName={savePairingName}
          onSavePc={savePairingPc}
        />
      </div>
    </div>
  );
}
