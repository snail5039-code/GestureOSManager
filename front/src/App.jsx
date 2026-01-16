import { useEffect, useMemo, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage";

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

    if (theme === "devil") {
      document.body.style.cursor = "crosshair";
    } else {
      document.body.style.cursor = "auto";
    }

    console.log("data-theme =", theme);
  }, [theme]);

  // ✅ TitleBar에 올릴 "연결/잠금/모드" 미니 상태
  const agentStatus = useMemo(() => {
    return {
      connected: !!hudFeed?.connected,
      locked: !!hudFeed?.locked,
      mode: hudFeed?.mode ?? "DEFAULT",
      modeText: hudFeed?.modeText ?? undefined, // TitleBar에서 modeText 우선 사용
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
        agentStatus={agentStatus} // ✅ 추가
      />

      <main
        className={
          screen === "dashboard" ? "flex-1 overflow-auto" : "flex-1 overflow-hidden"
        }
      >
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

        {screen === "rush" && (
          <Rush3DPage
            status={hudFeed?.status}
            connected={hudFeed?.connected ?? true}
          />
        )}
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
    </div>
  );
}
