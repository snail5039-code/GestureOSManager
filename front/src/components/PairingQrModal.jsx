import { useEffect, useMemo, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

export default function PairingQrModal({
  open,
  onClose,
  pairing,
  onSaveName,
  onSavePc,
}) {
  const [nameDraft, setNameDraft] = useState("");
  const [saving, setSaving] = useState(false);

  // pairing.name이 바뀌면 입력칸도 동기화
  useEffect(() => {
    setNameDraft(String(pairing?.name || ""));
  }, [pairing?.name]);

  // candidates 안전 추출
  const candidates = Array.isArray(pairing?.candidates) ? pairing.candidates : [];

  const payload = useMemo(() => {
    const pc = String(pairing?.pc || "").trim();
    const httpPort = Number(pairing?.httpPort || 0);
    const udpPort = Number(pairing?.udpPort || 0);
    const name = encodeURIComponent(String(pairing?.name || "PC"));

    if (!pc || !httpPort || !udpPort) return "";
    return `gestureos://pair?pc=${pc}&http=${httpPort}&udp=${udpPort}&name=${name}`;
  }, [pairing]);

  const canShow = !!payload;

  const copy = async () => {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload);
    } catch {
      // noop
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[99999] flex items-center justify-center bg-black/60 px-4 py-6"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div
        className={cn(
          "w-full max-w-[680px] max-h-[85vh] overflow-auto",
          "rounded-3xl ring-1 p-6",
          "bg-base-200 text-base-content border border-base-300/60",
          "shadow-2xl"
        )}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-base font-semibold">폰 페어링</div>
            <div className="text-xs opacity-70 mt-1">
              QR을 스캔하면 IP/포트가 자동 설정됩니다.
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className={cn(
              "h-9 w-9 grid place-items-center rounded-xl ring-1",
              "bg-base-100/30 ring-base-300/60",
              "transition-all duration-150",
              "hover:bg-base-100/60 hover:-translate-y-[1px] hover:shadow-sm",
              "active:translate-y-0 active:shadow-none"
            )}
            title="닫기"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="mt-5 flex flex-col md:flex-row gap-5">
          {/* LEFT: info */}
          <div className="flex-1 min-w-0">
            <div className="rounded-2xl ring-1 bg-base-100/25 ring-base-300/50 p-5">
              <div className="text-xs opacity-70">연결 정보</div>

              <div className="mt-3 grid grid-cols-[72px_1fr] gap-y-2 text-sm">
                <div className="opacity-70">PC</div>
                <div
                  className="text-right font-semibold truncate min-w-0"
                  title={pairing?.pc || ""}
                >
                  {pairing?.pc || "-"}
                </div>

                {/* ✅ IP 후보 */}
                {candidates.length > 0 && (
                  <>
                    <div className="opacity-70 text-[12px]">IP 후보</div>
                    <div className="flex justify-end">
                      <div className="flex flex-wrap gap-2 justify-end">
                        {candidates.map((ip) => {
                          const active = String(ip) === String(pairing?.pc);
                          return (
                            <button
                              key={ip}
                              type="button"
                              disabled={!onSavePc || saving}
                              onClick={async () => {
                                if (!onSavePc) return;
                                setSaving(true);
                                try {
                                  await onSavePc(ip);
                                } finally {
                                  setSaving(false);
                                }
                              }}
                              className={cn(
                                "px-3 py-1.5 rounded-xl text-[11px] font-semibold ring-1",
                                "transition-all duration-150 whitespace-nowrap",
                                active
                                  ? "bg-emerald-500/15 ring-emerald-400/30"
                                  : "bg-base-100/25 ring-base-300/50 hover:bg-base-100/45",
                                (!onSavePc || saving) && "opacity-60 cursor-not-allowed"
                              )}
                              title="클릭하면 PC IP로 저장"
                            >
                              {ip}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </>
                )}

                <div className="opacity-70">HTTP</div>
                <div className="text-right font-semibold">
                  {pairing?.httpPort ?? "-"}
                </div>

                <div className="opacity-70">UDP</div>
                <div className="text-right font-semibold">
                  {pairing?.udpPort ?? "-"}
                </div>

                {/* ✅ Name: 입력 */}
                <div className="opacity-70">Name</div>
                <div className="min-w-0 flex justify-end">
                  <input
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    className={cn(
                      "w-[220px] max-w-full text-right",
                      "px-3 py-2 rounded-xl ring-1",
                      "bg-base-100/25 ring-base-300/50",
                      "text-sm font-semibold outline-none",
                      "focus:ring-base-300/80 focus:bg-base-100/35"
                    )}
                    placeholder="PC"
                  />
                </div>
              </div>

              {/* Buttons */}
              <div className="mt-5 flex flex-wrap gap-2">
                {/* ✅ 이름 저장 */}
                <button
                  type="button"
                  disabled={!onSaveName || saving}
                  onClick={async () => {
                    if (!onSaveName) return;
                    setSaving(true);
                    try {
                      await onSaveName(nameDraft);
                    } finally {
                      setSaving(false);
                    }
                  }}
                  className={cn(
                    "px-4 py-2 rounded-2xl text-xs font-semibold ring-1",
                    "transition-all duration-150 whitespace-nowrap",
                    (!onSaveName || saving)
                      ? "opacity-50 cursor-not-allowed bg-base-100/20 ring-base-300/40"
                      : "bg-base-100/35 ring-base-300/60 hover:bg-base-100/60 hover:-translate-y-[1px] hover:shadow-sm"
                  )}
                >
                  {saving ? "저장 중..." : "이름 저장"}
                </button>

                <button
                  type="button"
                  onClick={copy}
                  disabled={!canShow}
                  className={cn(
                    "px-4 py-2 rounded-2xl text-xs font-semibold ring-1",
                    "transition-all duration-150 whitespace-nowrap",
                    canShow
                      ? "bg-base-100/35 ring-base-300/60 hover:bg-base-100/60 hover:-translate-y-[1px] hover:shadow-sm"
                      : "opacity-50 cursor-not-allowed bg-base-100/20 ring-base-300/40"
                  )}
                >
                  페어링 문자열 복사
                </button>

                <button
                  type="button"
                  onClick={() => onClose?.()}
                  className={cn(
                    "px-4 py-2 rounded-2xl text-xs font-semibold ring-1",
                    "bg-base-100/20 ring-base-300/50 hover:bg-base-100/45 transition whitespace-nowrap"
                  )}
                >
                  닫기
                </button>
              </div>

              {/* URI box */}
              <div className="mt-4">
                <div className="text-[11px] opacity-60 mb-1">페어링 URI</div>
                <div
                  className={cn(
                    "text-[11px] opacity-70 break-all",
                    "rounded-xl ring-1 bg-base-100/20 ring-base-300/40",
                    "p-3 max-h-20 overflow-auto"
                  )}
                >
                  {payload || "pairing 정보가 없습니다. (/api/pairing 확인)"}
                </div>
              </div>
            </div>

            <div className="mt-3 text-[11px] opacity-55">
              팁: 스캔이 잘 안되면 창을 크게 하고, QR을 더 크게 표시하세요.
            </div>
          </div>

          {/* RIGHT: QR */}
          <div className="shrink-0 w-full md:w-[320px]">
            <div className="rounded-2xl ring-1 bg-base-100/25 ring-base-300/50 p-5 flex items-center justify-center">
              {canShow ? (
                <div className="bg-white rounded-2xl p-4 ring-1 ring-black/10 shadow-sm">
                  <QRCodeCanvas value={payload} size={248} includeMargin />
                </div>
              ) : (
                <div className="text-sm opacity-70">QR 생성 불가</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
