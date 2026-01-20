import { useEffect, useMemo, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage";
import PairingQrModal from "./components/PairingQrModal";
import TrainingLab from "./pages/TrainingLab";
import { THEME } from "./theme/themeTokens";

const VALID_THEMES = new Set(["dark", "light", "neon", "rose", "devil"]);

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

export default function App() {
  // ✅ WEB HUD(AgentHud) ON/OFF 상태 (기본 ON, 저장)
  const [hudOn, setHudOn] = useState(() => {
    const v = localStorage.getItem("hudOn");
    return v === null ? true : v === "1";
  });

  // ✅ OS HUD(Python Overlay) ON/OFF 상태 (기본 ON, 저장)
  const [osHudOn, setOsHudOn] = useState(() => {
    const v = localStorage.getItem("osHudOn");
    return v === null ? true : v === "1";
  });

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

  // 화면 전환
  const [screen, setScreen] = useState("dashboard");

  // Dashboard에서 올라오는 HUD 표시용 데이터
  const [hudFeed, setHudFeed] = useState(null);

  // Dashboard의 액션(함수들)을 ref에 저장
  const hudActionsRef = useRef({});

  // ✅ 페어링 모달 & 데이터
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

  const savePairingName = async (nextName) => {
    const name = String(nextName || "").trim() || "PC";
    try {
      await fetch("/api/pairing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch {}
    refreshPairing();
  };

  const savePairingPc = async (nextPc) => {
    const pc = String(nextPc || "").trim();
    if (!pc) return;

    try {
      await fetch("/api/pairing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pc }),
      });
    } catch {}
    refreshPairing();
  };

  useEffect(() => {
    const cleanup = refreshPairing();
    return cleanup;
  }, []);

  // ✅ 테마 state (유효성 체크 + 저장)
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

  // ✅ TitleBar에 올릴 "연결/잠금/모드" 미니 상태
  const agentStatus = useMemo(() => {
    return {
      connected: !!hudFeed?.connected,
      locked: !!hudFeed?.locked,
      mode: hudFeed?.mode ?? "DEFAULT",
      modeText: hudFeed?.modeText ?? undefined,
    };
  }, [hudFeed]);

  return (
    <div
      data-theme={theme}
      className={cn(
        // ✅ 화면 전체를 정확히 먹도록
        "w-[100dvw] h-[100dvh] flex flex-col overflow-hidden min-w-0 min-h-0 relative",
        // ✅ 전체 창 배경색은 여기서 통일
        t.page
      )}
    >
      {/* ✅ 배경은 App 전체에 “fixed”로 깔아야 오른쪽/아래가 안 비고 항상 채워짐 */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div className={cn("absolute -top-40 -left-40 h-[520px] w-[520px] rounded-full blur-3xl", t.glow1)} />
        <div className={cn("absolute -bottom-52 -right-48 h-[560px] w-[560px] rounded-full blur-3xl", t.glow2)} />
        <div className={cn("absolute inset-0 bg-[size:60px_60px]", t.grid)} />
      </div>

      {/* TitleBar는 항상 위 */}
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

      {/* ✅ main은 투명(배경은 App fixed가 담당), 스크롤은 여기 한 곳만 */}
      <main
        className={cn(
          "relative z-10 flex-1 min-h-0 min-w-0",
          screen === "rush" ? "overflow-hidden" : "overflow-auto"
        )}
      >
        {/* Dashboard */}
        <div className={cn(screen === "dashboard" ? "block" : "hidden", "w-full min-w-0")}>
          <Dashboard
            hudOn={hudOn}
            onToggleHud={toggleHud}
            onHudState={setHudFeed}
            onHudActions={(actions) => {
              hudActionsRef.current = actions || {};
            }}
            theme={theme}
          />
        </div>

        {/* Rush */}
        {screen === "rush" && (
          <Rush3DPage status={hudFeed?.status} connected={hudFeed?.connected ?? true} />
        )}

        {/* Settings */}
        {screen === "settings" && <Settings theme={theme} />}

        {/* Training Lab */}
        {screen === "train" && <TrainingLab theme={theme} />}
      </main>

      {/* HUD/Modal은 제일 위 레이어 */}
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
