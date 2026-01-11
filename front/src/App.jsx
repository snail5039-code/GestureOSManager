import { useEffect, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage"; // ✅ 파일 위치에 맞게 조정

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

  // ✅ 화면 전환: dashboard | rush
  const [screen, setScreen] = useState("dashboard");

  // ✅ Dashboard에서 올라오는 HUD 표시용 데이터
  const [hudFeed, setHudFeed] = useState(null);

  // ✅ Dashboard의 액션(함수들)을 ref에 저장
  const hudActionsRef = useRef({});

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-[#0b1020]">
      {/* ✅ 타이틀바에서 HUD 토글 + 화면 전환 */}
      <TitleBar
        hudOn={hudOn}
        onToggleHud={toggleHud}
        screen={screen}
        onChangeScreen={setScreen}
      />

      {/* ✅ 화면에 따라 스크롤 동작 변경 */}
      <main className={screen === "rush" ? "flex-1 overflow-hidden" : "flex-1 overflow-auto"}>
        {/* Dashboard는 계속 살아있게(폴링 계속) */}
        {/* Dashboard는 계속 살아있게 */}
        <div className={screen === "dashboard" ? "block" : "hidden"}>
          <Dashboard
            hudOn={hudOn}
            onToggleHud={toggleHud}
            onHudState={setHudFeed}
            onHudActions={(actions) => {
              hudActionsRef.current = actions || {};
            }}
          />
        </div>

        {/* ✅ Rush는 보일 때만 마운트 (캔버스 0x0 문제 해결) */}
        {screen === "rush" && (
          <Rush3DPage status={hudFeed?.status} connected={hudFeed?.connected ?? true} />
        )}
      </main>

      {/* ✅ HUD는 App에서만 렌더링 */}
      {hudOn && (
        <AgentHud
          // 표시 데이터
          status={hudFeed?.status}
          connected={hudFeed?.connected ?? true}
          modeOptions={hudFeed?.modeOptions}
          // 액션(버튼 동작) 연결
          onSetMode={(m) => hudActionsRef.current.applyMode?.(m)}
          onEnableToggle={(next) =>
            next ? hudActionsRef.current.start?.() : hudActionsRef.current.stop?.()
          }
          onPreviewToggle={() => hudActionsRef.current.togglePreview?.()}
          // ✅ Lock: 백엔드 구현 여부에 따라 setLock(권장) 또는 lockToggle(대안)
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
