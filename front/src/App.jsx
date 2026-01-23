import { useEffect, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage";
import GamePage from "./pages/GamePage";

const VALID_THEMES = new Set(["dark", "light", "neon", "rose", "devil"]);

export default function App() {
  // HUD ON/OFF 상태 (기본 ON, 저장)
  const [hudOn, setHudOn] = useState(() => {
    const v = localStorage.getItem("hudOn");
    return v === null ? true : v === "1";
  });

  useEffect(() => {
    localStorage.setItem("hudOn", hudOn ? "1" : "0");
  }, [hudOn]);

  const toggleHud = () => setHudOn((x) => !x);

  // 화면 전환
// 화면 전환
const [screen, setScreen] = useState(() => {
  // 개발 중에는 gamePage로 바로 진입
  if (import.meta.env.DEV) return "gamePage";
  return "dashboard";
});

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
      document.body.style.cursor = "url('/cursor/devil.png') 16 16, auto";
    } else {
      document.body.style.cursor = "auto";
    }

    console.log("data-theme =", theme);
  }, [theme]);

  return (
    <div data-theme={theme} className="h-screen flex flex-col overflow-hidden">
      <TitleBar
        hudOn={hudOn}
        onToggleHud={toggleHud}
        screen={screen}
        onChangeScreen={setScreen}
        theme={theme}
        setTheme={setTheme}
      />

      <main className={screen === "dashboard" ? "flex-1 overflow-auto" : "flex-1 overflow-hidden"}>
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
          <Rush3DPage status={hudFeed?.status} connected={hudFeed?.connected ?? true} />
        )}
        {screen === "gamePage" && (
          <GamePage status={hudFeed?.status} connected={hudFeed?.connected ?? true} />
        )}
      </main>

      {hudOn && (
        <AgentHud
          status={hudFeed?.status}
          connected={hudFeed?.connected ?? true}
          modeOptions={hudFeed?.modeOptions}
          onSetMode={(m) => hudActionsRef.current.applyMode?.(m)}
          onEnableToggle={(next) => (next ? hudActionsRef.current.start?.() : hudActionsRef.current.stop?.())}
          onPreviewToggle={() => hudActionsRef.current.togglePreview?.()}
          onLockToggle={(nextLocked) => {
            if (hudActionsRef.current.setLock) return hudActionsRef.current.setLock(nextLocked);
            return hudActionsRef.current.lockToggle?.();
          }}
          onRequestHide={() => setHudOn(false)}
        />
      )}
    </div>
  );
}
