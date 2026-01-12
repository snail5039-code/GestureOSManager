import { useEffect, useMemo, useRef, useState } from "react";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

/**
 * VKeyPage
 * - App에서 내려주는 status를 사용
 * - pointerX/Y 또는 left/rightPointerX/Y로 "키 위" 하이라이트
 * - tapSeq 변화(증가)를 에어탭으로 보고 tapX/tapY 위치의 키를 확정 입력
 *
 * 이번 단계 목표(최소):
 * 1) 화면에 가상 키보드가 뜬다
 * 2) 포인터가 키 위에 있으면 하이라이트 된다
 * 3) tapSeq가 바뀌면(에어탭) 해당 키가 입력되어 상단 텍스트에 쌓인다
 */

const KEY_ROWS = [
  ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
  ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
  ["Z", "X", "C", "V", "B", "N", "M"],
];

function normalizeKey(k) {
  if (!k) return null;
  if (k === "SPACE") return " ";
  if (k === "ENTER") return "\n";
  if (k === "BKSP") return "BKSP";
  return String(k);
}

export default function VKeyPage({ status }) {
  const rootRef = useRef(null);

  // 입력 결과(일단 UI에만 쌓음)
  const [text, setText] = useState("");

  // hover 상태(양손)
  const [hoverL, setHoverL] = useState(null);
  const [hoverR, setHoverR] = useState(null);
  const [lastTapKey, setLastTapKey] = useState(null);

  // tap 중복 방지
  const lastTapSeqRef = useRef(null);

  // 좌표(0~1) -> 화면 좌표(px)
  const toClientXY = (nx, ny) => {
    const el = rootRef.current;
    if (!el) return null;
    if (typeof nx !== "number" || typeof ny !== "number") return null;
    const r = el.getBoundingClientRect();
    const x = r.left + nx * r.width;
    const y = r.top + ny * r.height;
    return { x, y };
  };

  // elementFromPoint로 "현재 키" 찾기
  const pickKeyAt = (nx, ny) => {
    const pt = toClientXY(nx, ny);
    if (!pt) return null;
    const hit = document.elementFromPoint(pt.x, pt.y);
    const btn = hit?.closest?.("[data-vkey]");
    return btn?.getAttribute?.("data-vkey") || null;
  };

  // 두 손 포인터 값
  const pointers = useMemo(() => {
    const lx = status?.leftPointerX;
    const ly = status?.leftPointerY;
    const rx = status?.rightPointerX;
    const ry = status?.rightPointerY;

    // fallback: 단일 포인터만 오는 경우
    const px = status?.pointerX;
    const py = status?.pointerY;

    return {
      left: typeof lx === "number" && typeof ly === "number" ? { x: lx, y: ly } : null,
      right: typeof rx === "number" && typeof ry === "number" ? { x: rx, y: ry } : null,
      single: typeof px === "number" && typeof py === "number" ? { x: px, y: py } : null,
    };
  }, [status]);

  // hover 업데이트(폴링 주기면 충분)
  useEffect(() => {
    const l = pointers.left || null;
    const r = pointers.right || pointers.single || null;

    setHoverL(l ? pickKeyAt(l.x, l.y) : null);
    setHoverR(r ? pickKeyAt(r.x, r.y) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointers.left?.x, pointers.left?.y, pointers.right?.x, pointers.right?.y, pointers.single?.x, pointers.single?.y]);

  // tapSeq가 바뀌면 "입력 확정"
  useEffect(() => {
    const tapSeq = status?.tapSeq;
    if (tapSeq === null || tapSeq === undefined) return;

    // 첫 수신은 저장만
    if (lastTapSeqRef.current === null) {
      lastTapSeqRef.current = tapSeq;
      return;
    }
    if (tapSeq === lastTapSeqRef.current) return;

    lastTapSeqRef.current = tapSeq;

    const k = pickKeyAt(status?.tapX, status?.tapY);
    if (!k) return;

    setLastTapKey(k);
    setTimeout(() => setLastTapKey(null), 120);

    const nk = normalizeKey(k);
    if (!nk) return;

    setText((prev) => {
      if (nk === "BKSP") return prev.length ? prev.slice(0, -1) : prev;
      if (nk === "\n") return prev + "\n";
      return prev + nk;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.tapSeq]);

  // 포인터 원(시각화)
  const renderPointer = (p, tone) => {
    if (!p) return null;
    const pt = toClientXY(p.x, p.y);
    if (!pt) return null;
    return (
      <div
        className={cn(
          "pointer-events-none absolute -translate-x-1/2 -translate-y-1/2",
          "h-5 w-5 rounded-full ring-2",
          tone === "L" ? "bg-sky-400/25 ring-sky-300/60" : "bg-emerald-400/25 ring-emerald-300/60"
        )}
        style={{ left: pt.x, top: pt.y }}
      />
    );
  };

  const KeyBtn = ({ k, wide }) => {
    const active = k === hoverL || k === hoverR || k === lastTapKey;
    const pressed = k === lastTapKey;

    return (
      <div
        data-vkey={k}
        className={cn(
          "select-none",
          "h-12 rounded-xl flex items-center justify-center",
          "ring-1 ring-white/10",
          "bg-white/5 hover:bg-white/8",
          active && "ring-white/30 bg-white/10",
          pressed && "scale-[0.98]",
          wide ? "flex-[2]" : "flex-1"
        )}
      >
        <span className={cn("text-sm font-semibold", pressed ? "text-white" : "text-white/85")}>
          {k === "SPACE" ? "Space" : k === "BKSP" ? "Back" : k === "ENTER" ? "Enter" : k}
        </span>
      </div>
    );
  };

  return (
    <div ref={rootRef} className="relative h-full w-full overflow-hidden bg-[#070c16] text-slate-100">
      {/* background */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 -left-40 h-[520px] w-[520px] rounded-full bg-sky-500/10 blur-3xl" />
        <div className="absolute -bottom-52 -right-48 h-[560px] w-[560px] rounded-full bg-emerald-500/8 blur-3xl" />
        <div className="absolute inset-0 opacity-[0.08] bg-[linear-gradient(to_right,rgba(255,255,255,.10)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,.10)_1px,transparent_1px)] bg-[size:60px_60px]" />
      </div>

      {/* content */}
      <div className="relative h-full flex flex-col">
        <div className="px-6 pt-6">
          <div className="text-sm text-white/70">Virtual Keyboard (VKEY)</div>
          <div className="mt-2 rounded-2xl bg-slate-950/45 ring-1 ring-white/10 p-4">
            <div className="text-xs text-white/60 mb-2">Typed (UI only)</div>
            <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-white/90 min-h-[84px]">
              {text || "(tap to type...)"}
            </pre>
          </div>

          <div className="mt-3 text-xs text-white/60">
            status.mode: <span className="text-white/80">{status?.mode ?? "-"}</span> · tapSeq:{" "}
            <span className="text-white/80">{status?.tapSeq ?? "-"}</span>
          </div>
        </div>

        {/* keyboard */}
        <div className="mt-auto px-6 pb-8">
          <div className="mx-auto max-w-[980px] rounded-3xl bg-slate-950/35 ring-1 ring-white/10 p-5 shadow-[0_18px_60px_rgba(0,0,0,0.45)]">
            <div className="space-y-3">
              {KEY_ROWS.map((row, i) => (
                <div key={i} className={cn("flex gap-2", i === 1 && "px-5", i === 2 && "px-10")}>
                  {row.map((k) => (
                    <KeyBtn key={k} k={k} />
                  ))}
                </div>
              ))}
              <div className="flex gap-2">
                <KeyBtn k="BKSP" wide />
                <KeyBtn k="SPACE" wide />
                <KeyBtn k="ENTER" wide />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* pointers overlay */}
      {renderPointer(pointers.left, "L")}
      {renderPointer(pointers.right || pointers.single, "R")}
    </div>
  );
}
