import { useEffect, useMemo, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage";
import PairingQrModal from "./components/PairingQrModal";
import TrainingLab from "./pages/TrainingLab";

const VALID_THEMES = new Set(["dark", "light", "neon", "rose", "devil"]);

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

  // ✅ WEB HUD: 저장만 (절대 /api/hud/show 호출하지 않음!)
  useEffect(() => {
    localStorage.setItem("hudOn", hudOn ? "1" : "0");
  }, [hudOn]);

  // ✅ OS HUD: 저장 + 서버 호출 (/api/hud/show)
  useEffect(() => {
    localStorage.setItem("osHudOn", osHudOn ? "1" : "0");
    fetch(`/api/hud/show?enabled=${osHudOn ? "true" : "false"}`, {
      method: "POST",
    }).catch(() => { });
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

  // ✅ 서버에서 pairing 정보 최신화
  const refreshPairing = () => {
    let cancelled = false;

    fetch("/api/pairing")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        if (cancelled || !data) return;
        setPairing((prev) => ({ ...prev, ...data }));
      })
      .catch(() => { });

    return () => {
      cancelled = true;
    };
  };

  // ✅ Name 저장(POST) → 저장 후 즉시 refresh
  const savePairingName = async (nextName) => {
    const name = String(nextName || "").trim() || "PC";

    try {
      await fetch("/api/pairing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch {
      // noop
    }

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
    } catch {
      // noop
    }

    refreshPairing();
  };

  // 앱 시작 시 1회 로딩
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
    if (!VALID_THEMES.has(v)) {
      console.warn("[theme] invalid value from TitleBar:", next);
      return;
    }
    _setTheme(v);
  };

  // ✅ DaisyUI + html attribute 적용 + localStorage 저장
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);

    // 기존 로직 유지(조금 중복이지만 그대로 둠)
    if (theme === "dark") document.body.style.cursor = "crosshair";
    else document.body.style.cursor = "auto";

    if (theme === "light") document.body.style.cursor = "crosshair";
    else document.body.style.cursor = "auto";

    if (theme === "neon") document.body.style.cursor = "crosshair";
    else document.body.style.cursor = "auto";

    if (theme === "rose") document.body.style.cursor = "crosshair";
    else document.body.style.cursor = "auto";

    if (theme === "devil") document.body.style.cursor = "crosshair";
    else document.body.style.cursor = "auto";

    console.log("data-theme =", theme);
  }, [theme]);

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
    <div data-theme={theme} className="h-screen flex flex-col overflow-hidden">
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

      <main
        className={
          screen === "rush" ? "flex-1 overflow-hidden" : "flex-1 overflow-auto"
        }
      >
        {/* Dashboard */}
        <div className={screen === "dashboard" ? "block" : "hidden"}>
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
          <Rush3DPage
            status={hudFeed?.status}
            connected={hudFeed?.connected ?? true}
          />
        )}

        {/* Settings */}
        {screen === "settings" && <Settings theme={theme} />}

        {/* Training Lab */}
        {screen === "train" && <TrainingLab theme={theme} />}
      </main>

      {/* ✅ WEB HUD(AgentHud)만 hudOn으로 제어 */}
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
            if (hudActionsRef.current.setLock)
              return hudActionsRef.current.setLock(nextLocked);
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
  );
}
