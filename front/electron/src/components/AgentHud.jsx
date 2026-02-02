import { useEffect, useMemo, useState } from "react";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

/* ---------------------------
   Small UI Primitives
---------------------------- */
function Badge({ children, tone = "neutral" }) {
  const toneCls =
    tone === "ok"
      ? "bg-emerald-500/10 ring-emerald-400/25"
      : tone === "bad"
      ? "bg-rose-500/10 ring-rose-400/25"
      : tone === "warn"
      ? "bg-amber-500/10 ring-amber-400/25"
      : "bg-base-100/10 ring-base-300/45";

  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1",
        "text-base-content",
        toneCls
      )}
    >
      {children}
    </span>
  );
}

function KeyVal({ k, v, tone = "neutral" }) {
  const toneCls =
    tone === "ok"
      ? "text-emerald-200"
      : tone === "bad"
      ? "text-rose-200"
      : tone === "warn"
      ? "text-amber-200"
      : "text-base-content";

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-base-100/8 ring-1 ring-base-300/40 px-3 py-2">
      <div className="text-[11px] opacity-70 whitespace-nowrap">{k}</div>
      <div className={cn("text-xs font-semibold whitespace-nowrap", toneCls)}>{String(v ?? "-")}</div>
    </div>
  );
}

function IconX() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-80">
      <path d="M18 6 6 18M6 6l12 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
function IconBolt() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-85">
      <path d="M13 2 3 14h8l-1 8 10-12h-8l1-8Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}
function IconLock() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-85">
      <path
        d="M7 11V8a5 5 0 0 1 10 0v3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M6 11h12v10H6V11Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function IconEye() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-85">
      <path
        d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}
function IconLayers() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="opacity-85">
      <path
        d="M12 3 2 9l10 6 10-6-10-6Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M2 15l10 6 10-6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ActionBtn({ icon, label, tone = "neutral", onClick, disabled }) {
  const base =
    "w-full rounded-lg px-3 py-2 text-sm font-semibold ring-1 transition inline-flex items-center justify-center gap-2";
  const toneCls =
    tone === "primary"
      ? "bg-primary/15 ring-primary/25 hover:bg-primary/22"
      : tone === "danger"
      ? "bg-rose-500/12 ring-rose-400/25 hover:bg-rose-500/18"
      : "bg-base-100/10 ring-base-300/45 hover:bg-base-100/16";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(base, toneCls, disabled && "opacity-50 pointer-events-none")}
    >
      {icon}
      <span className="whitespace-nowrap">{label}</span>
    </button>
  );
}

/* ---------------------------
   Mode Picker (Overlay)
---------------------------- */
function ModeOverlay({ open, modes, currentMode, onPick, onClose }) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100000] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onMouseDown={onClose} />

      <div
        className={cn(
          "relative w-full max-w-2xl",
          "rounded-xl ring-1 border border-base-300/60",
          "bg-base-200/92 text-base-content shadow-2xl",
          "backdrop-blur-md"
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-base-300/45 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold whitespace-nowrap">모드 선택</div>
            <div className="text-[12px] opacity-70 truncate">
              현재 모드: <span className="font-semibold opacity-100">{currentMode}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-9 w-9 grid place-items-center rounded-lg ring-1 bg-base-100/10 ring-base-300/45 hover:bg-base-100/16"
            title="닫기"
          >
            <IconX />
          </button>
        </div>

        <div className="p-5 grid grid-cols-2 gap-3">
          {modes.map((m) => {
            const active = String(currentMode).toUpperCase() === String(m).toUpperCase();
            return (
              <button
                key={m}
                type="button"
                onClick={() => onPick?.(m)}
                className={cn(
                  "rounded-lg ring-1 px-4 py-3 text-left transition",
                  active
                    ? "bg-primary/12 ring-primary/25"
                    : "bg-base-100/8 ring-base-300/45 hover:bg-base-100/14"
                )}
              >
                <div className="text-sm font-semibold whitespace-nowrap">{m}</div>
                <div className="mt-1 text-[12px] opacity-70 line-clamp-2">
                  {m === "MOUSE" && "커서/클릭/드래그/스크롤"}
                  {m === "KEYBOARD" && "키보드 입력/단축키"}
                  {m === "PRESENTATION" && "발표 제어(다음/이전 등)"}
                  {m === "DRAW" && "그리기/펜 입력"}
                  {m === "DEFAULT" && "기본(비활성/대기)"}
                  {!["MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "DEFAULT"].includes(m) && "사용자 정의 모드"}
                </div>
              </button>
            );
          })}
        </div>

        <div className="px-5 pb-5 text-[11px] opacity-60">
          ESC로 닫기. 모드는 즉시 적용됩니다.
        </div>
      </div>
    </div>
  );
}

/* ---------------------------
   Agent HUD
---------------------------- */
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
  const gesture = (s.gesture ?? "NONE").toString().toUpperCase();

  const fps = useMemo(() => {
    const v = Number(s.fps);
    return Number.isFinite(v) ? v.toFixed(1) : "-";
  }, [s.fps]);

  const canMove = !!s.canMove;
  const canClick = !!s.canClick;
  const scrollActive = !!s.scrollActive;

  const connTone = connected ? "ok" : "bad";
  const enTone = enabled ? "ok" : "bad";
  const lockTone = locked ? "warn" : "ok";

  return (
    <>
      {/* 외곽 클릭 통과, 카드만 클릭 */}
      <div className="fixed right-4 top-14 z-[9998] pointer-events-none">
        <div
          className={cn(
            "pointer-events-auto w-[340px]",
            "rounded-xl ring-1 border border-base-300/55",
            "bg-base-200/78 text-base-content shadow-2xl",
            "backdrop-blur-md"
          )}
        >
          {/* Header */}
          <div className="px-4 py-3 border-b border-base-300/45 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold whitespace-nowrap">HUD</div>
              <div className="text-[12px] opacity-70 truncate">
                에이전트 상태 요약
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Badge tone={connTone}>HTTP {connected ? "OK" : "OFF"}</Badge>
              <button
                type="button"
                className="h-8 w-8 grid place-items-center rounded-lg hover:bg-base-100/12"
                onClick={() => onRequestHide?.()}
                title="Hide HUD"
              >
                <IconX />
              </button>
            </div>
          </div>

          {/* KPI Row */}
          <div className="px-4 pt-3">
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-lg bg-base-100/8 ring-1 ring-base-300/40 px-3 py-2">
                <div className="text-[11px] opacity-70 whitespace-nowrap">Enabled</div>
                <div className={cn("text-sm font-semibold whitespace-nowrap", enabled ? "text-emerald-200" : "text-rose-200")}>
                  {enabled ? "ON" : "OFF"}
                </div>
              </div>
              <div className="rounded-lg bg-base-100/8 ring-1 ring-base-300/40 px-3 py-2">
                <div className="text-[11px] opacity-70 whitespace-nowrap">Locked</div>
                <div className={cn("text-sm font-semibold whitespace-nowrap", locked ? "text-amber-200" : "text-emerald-200")}>
                  {locked ? "ON" : "OFF"}
                </div>
              </div>
              <div className="rounded-lg bg-base-100/8 ring-1 ring-base-300/40 px-3 py-2">
                <div className="text-[11px] opacity-70 whitespace-nowrap">FPS</div>
                <div className="text-sm font-semibold whitespace-nowrap">{fps}</div>
              </div>
            </div>
          </div>

          {/* Details */}
          <div className="px-4 pt-3">
            <div className="grid grid-cols-2 gap-2">
              <KeyVal k="Mode" v={mode} tone="neutral" />
              <KeyVal k="Gesture" v={gesture} tone="neutral" />
              <KeyVal k="Move" v={canMove ? "YES" : "NO"} tone={canMove ? "ok" : "neutral"} />
              <KeyVal k="Click" v={canClick ? "YES" : "NO"} tone={canClick ? "ok" : "neutral"} />
              <KeyVal k="Scroll" v={scrollActive ? "ON" : "OFF"} tone={scrollActive ? "ok" : "neutral"} />
              <KeyVal k="HTTP" v={connected ? "OK" : "OFF"} tone={connTone} />
            </div>
          </div>

          {/* Actions */}
          <div className="px-4 py-4">
            <div className="grid grid-cols-2 gap-2">
              <ActionBtn
                icon={<IconBolt />}
                label={enabled ? "Disable" : "Enable"}
                tone={enabled ? "danger" : "primary"}
                onClick={() => onEnableToggle?.(!enabled)}
              />
              <ActionBtn
                icon={<IconLock />}
                label="Lock 토글"
                onClick={() => onLockToggle?.(!locked)}
              />
              <ActionBtn
                icon={<IconLayers />}
                label="Mode 변경"
                tone="primary"
                onClick={() => setOverlayOpen(true)}
              />
              <ActionBtn
                icon={<IconEye />}
                label="Preview 토글"
                onClick={() => onPreviewToggle?.()}
              />
            </div>

            <div className="mt-3 text-[11px] opacity-60 leading-relaxed">
              문제 발생 시: <span className="font-semibold opacity-100">HTTP / Enabled / Mode</span>부터 확인.
            </div>
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
