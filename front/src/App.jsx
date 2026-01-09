import { useEffect, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import AgentHud from "./components/AgentHud";

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

  // ✅ Dashboard에서 올라오는 HUD 표시용 데이터
  const [hudFeed, setHudFeed] = useState(null);

  // ✅ Dashboard의 액션(함수들)을 ref에 저장
  const hudActionsRef = useRef({});

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-[#0b1020]">
      {/* ✅ 타이틀바에서 HUD 토글 */}
      <TitleBar hudOn={hudOn} onToggleHud={toggleHud} />

      {/* ✅ 내용만 스크롤 */}
      <main className="flex-1 overflow-auto">
        <Dashboard
          hudOn={hudOn}
          onToggleHud={toggleHud}
          onHudState={setHudFeed}
          onHudActions={(actions) => {
            hudActionsRef.current = actions || {};
          }}
        />
      </main>

      {/* ✅ HUD는 App에서만 렌더링 (B 방식 핵심) */}
      {hudOn && (
        <AgentHud
          // 표시 데이터
          status={hudFeed?.status}
          connected={hudFeed?.connected ?? true}
          modeOptions={hudFeed?.modeOptions}
          // 액션(버튼 동작) 연결
          onSetMode={(m) => hudActionsRef.current.applyMode?.(m)}
          onEnableToggle={(next) =>
            next
              ? hudActionsRef.current.start?.()
              : hudActionsRef.current.stop?.()
          }
          onPreviewToggle={() => hudActionsRef.current.togglePreview?.()}
          // ✅ Lock: 백엔드 구현 여부에 따라 setLock(권장) 또는 lockToggle(대안)
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
