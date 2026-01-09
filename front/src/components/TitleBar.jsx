export default function TitleBar() {
  const onMin = () => window.managerWin?.minimize?.();
  const onMax = () => window.managerWin?.toggleMaximize?.();
  const onClose = () => window.managerWin?.close?.();

  return (
    <div
      className="h-11 flex items-center justify-between px-3 select-none border-b border-white/10 bg-gradient-to-b from-[#0b1020] to-[#070b14]"
      style={{ WebkitAppRegion: "drag" }} // 이 영역을 잡고 창 이동
      onDoubleClick={onMax} // 더블클릭하면 최대화/복구(윈도우 감성)
    >
      <div className="flex items-center gap-2 text-slate-200">
        <div className="w-6 h-6 rounded-md bg-white/10 flex items-center justify-center text-xs">
          GA
        </div>
        <span className="font-semibold text-sm">Gesture Agent Manager</span>
      </div>

      {/* 버튼은 드래그 영역에서 제외해야 클릭 가능 */}
      <div className="flex items-center gap-2" style={{ WebkitAppRegion: "no-drag" }}>
        <button
          className="w-10 h-8 rounded-md hover:bg-white/10 text-slate-200"
          onClick={onMin}
          title="Minimize"
        >
          —
        </button>
        <button
          className="w-10 h-8 rounded-md hover:bg-white/10 text-slate-200"
          onClick={onMax}
          title="Maximize"
        >
          □
        </button>
        <button
          className="w-10 h-8 rounded-md hover:bg-red-500/30 text-slate-200"
          onClick={onClose}
          title="Close"
        >
          ×
        </button>
      </div>
    </div>
  );
}
