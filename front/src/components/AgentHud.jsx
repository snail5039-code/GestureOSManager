import { useEffect, useMemo, useState } from "react";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function Pill({ label, value, tone = "slate" }) {
  const toneMap = {
    slate: "bg-slate-800/70 text-slate-100 border-slate-600/40",
    green: "bg-emerald-700/70 text-emerald-50 border-emerald-400/30",
    red: "bg-rose-700/70 text-rose-50 border-rose-400/30",
    amber: "bg-amber-700/70 text-amber-50 border-amber-400/30",
    blue: "bg-sky-700/70 text-sky-50 border-sky-400/30",
    purple: "bg-violet-700/70 text-violet-50 border-violet-400/30",
  };
  return (
    <div className={cn("inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs", toneMap[tone] ?? toneMap.slate)}>
      <span className="opacity-80">{label}</span>
      <span className="font-semibold">{String(value ?? "-")}</span>
    </div>
  );
}

function ModeOverlay({ open, modes, currentMode, onPick, onClose }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9999]">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="w-full max-w-xl rounded-2xl border border-white/10 bg-slate-900/85 p-5 shadow-2xl">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-lg font-semibold text-slate-100">Mode 선택</div>
              <div className="text-sm text-slate-300">
                현재 모드: <span className="font-semibold">{currentMode}</span>
              </div>
            </div>
            <button
              onClick={onClose}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 hover:bg-white/10"
            >
              닫기 (ESC)
            </button>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3">
            {modes.map((m) => {
              const active = String(currentMode).toUpperCase() === String(m).toUpperCase();
              return (
                <button
                  key={m}
                  onClick={() => onPick(m)}
                  className={cn(
                    "rounded-2xl border p-4 text-left transition",
                    active
                      ? "border-sky-400/40 bg-sky-500/15 text-sky-50"
                      : "border-white/10 bg-white/5 text-slate-100 hover:bg-white/10"
                  )}
                >
                  <div className="text-base font-semibold">{m}</div>
                  <div className="mt-1 text-xs text-slate-300">
                    {m === "MOUSE" && "커서/클릭/드래그/스크롤"}
                    {m === "KEYBOARD" && "키보드 입력/단축키"}
                    {m === "PRESENTATION" && "발표 제어(다음/이전 등)"}
                    {m === "DRAW" && "그리기/펜 입력"}
                    {m === "DEFAULT" && "기본(비활성/대기)"}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mt-4 text-xs text-slate-400">팁: 나중에 제스처로 열기 같은 확장 가능.</div>
        </div>
      </div>
    </div>
  );
}

export default function AgentHud({
  status,
  connected = true,
  modeOptions = ["MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "DEFAULT"],
  onSetMode,
  onEnableToggle,
  onLockToggle,
  onPreviewToggle,
  onRequestHide,
}) {
  const [overlayOpen, setOverlayOpen] = useState(false);

  const s = status ?? {};
  const enabled = !!s.enabled;
  const locked = !!s.locked;
  const mode = (s.mode ?? "UNKNOWN").toString().toUpperCase();
  const gesture = s.gesture ?? "NONE";

  const toneConn = connected ? "green" : "red";
  const toneEn = enabled ? "green" : "red";
  const toneLock = locked ? "amber" : "green";

  const fps = useMemo(() => {
    const v = Number(s.fps);
    return Number.isFinite(v) ? v.toFixed(1) : "-";
  }, [s.fps]);

  const canMove = !!s.canMove;
  const canClick = !!s.canClick;
  const scrollActive = !!s.scrollActive;

  useEffect(() => {
    if (!overlayOpen) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setOverlayOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [overlayOpen]);

  return (
    <>
      {/* 바깥은 클릭 통과, 카드만 클릭 가능 */}
      <div className="fixed right-4 top-14 z-[9998] pointer-events-none">
        <div className="pointer-events-auto w-[340px] rounded-2xl border border-white/10 bg-[#0b1020]/90 p-4 text-slate-100 shadow-xl backdrop-blur-md">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">HUD</div>
              <div className="mt-1 text-xs text-slate-300">상태 요약(항상 표시)</div>
            </div>

            <div className="flex items-center gap-2">
              <Pill label="HTTP" value={connected ? "OK" : "OFF"} tone={toneConn} />
              <button
                className="w-8 h-8 rounded-md hover:bg-white/10 text-slate-200"
                onClick={() => onRequestHide?.()}
                title="Hide HUD"
              >
                ×
              </button>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <Pill label="Enabled" value={enabled ? "ON" : "OFF"} tone={toneEn} />
            <Pill label="Locked" value={locked ? "ON" : "OFF"} tone={toneLock} />
            <Pill label="Mode" value={mode} tone="blue" />
            <Pill label="Gesture" value={gesture} tone="purple" />
            <Pill label="FPS" value={fps} tone="slate" />
            <Pill label="Move" value={canMove ? "YES" : "NO"} tone={canMove ? "green" : "slate"} />
            <Pill label="Click" value={canClick ? "YES" : "NO"} tone={canClick ? "green" : "slate"} />
            <Pill label="Scroll" value={scrollActive ? "ON" : "OFF"} tone={scrollActive ? "green" : "slate"} />
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2">
            <button
              onClick={() => onEnableToggle?.(!enabled)}
              className={cn(
                "rounded-xl border px-3 py-2 text-sm transition",
                enabled
                  ? "border-rose-400/30 bg-rose-500/15 hover:bg-rose-500/25"
                  : "border-emerald-400/30 bg-emerald-500/15 hover:bg-emerald-500/25"
              )}
            >
              {enabled ? "Disable" : "Enable"}
            </button>

            {/* ✅ Lock 토글 */}
            <button
              onClick={() => onLockToggle?.(!locked)}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm hover:bg-white/10"
            >
              Lock 토글
            </button>

            <button
              onClick={() => setOverlayOpen(true)}
              className="rounded-xl border border-sky-400/25 bg-sky-500/10 px-3 py-2 text-sm hover:bg-sky-500/20"
            >
              Mode 변경
            </button>

            <button
              onClick={() => onPreviewToggle?.()}
              className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm hover:bg-white/10"
            >
              Preview 토글
            </button>
          </div>

          <div className="mt-3 text-xs text-slate-400 leading-relaxed">
            문제 생기면 여기 값부터 본다: <span className="text-slate-200">Locked/Mode/HTTP</span>
          </div>
        </div>
      </div>

      <ModeOverlay
        open={overlayOpen}
        modes={modeOptions}
        currentMode={mode}
        onClose={() => setOverlayOpen(false)}
        onPick={(m) => {
          onSetMode?.(m);
          setOverlayOpen(false);
        }}
      />
    </>
  );
}
