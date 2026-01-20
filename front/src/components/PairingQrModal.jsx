import { useEffect, useMemo, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function StatusPill({ tone = "neutral", children, title }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 select-none",
        tone === "ok"
          ? "bg-emerald-500/15 ring-emerald-400/30"
          : tone === "bad"
          ? "bg-rose-500/15 ring-rose-400/30"
          : "bg-base-100/25 ring-base-300/50 opacity-90"
      )}
      title={title}
    >
      {children}
    </span>
  );
}

/**
 * PairingQrModal
 * - QR 페어링 문자열 생성
 * - 스트림 URL 열기(새 탭)
 * - 스트림 "간이 점검"(프론트만): <img> 로딩 시도 + 타임아웃
 * - 배포용 안내 문구 표시
 */
export default function PairingQrModal({ open, onClose, pairing }) {
  const payload = useMemo(() => {
    const pc = String(pairing?.pc || "").trim();
    const httpPort = Number(pairing?.httpPort || 0);
    const udpPort = Number(pairing?.udpPort || 0);
    const name = encodeURIComponent(String(pairing?.name || "PC"));

    if (!pc || !httpPort || !udpPort) return "";
    return `gestureos://pair?pc=${pc}&http=${httpPort}&udp=${udpPort}&name=${name}`;
  }, [pairing]);

  const streamUrl = useMemo(() => {
    const pc = String(pairing?.pc || "").trim();
    const httpPort = Number(pairing?.httpPort || 0);
    if (!pc || !httpPort) return "";
    return `http://${pc}:${httpPort}/mjpeg`;
  }, [pairing]);

  const canShow = !!payload;

  const [streamCheck, setStreamCheck] = useState({
    status: "idle", // idle | checking | ok | fail
    ms: null,
    error: "",
  });

  useEffect(() => {
    if (!open) return;
    // 모달 열릴 때마다 체크 상태 초기화
    setStreamCheck({ status: "idle", ms: null, error: "" });
  }, [open, pairing?.pc, pairing?.httpPort]);

  const copy = async () => {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload);
    } catch {
      // noop
    }
  };

  const openStream = () => {
    if (!streamUrl) return;
    window.open(streamUrl, "_blank", "noopener,noreferrer");
  };

  /**
   * 스트림 점검(프론트만)
   * - MJPEG는 fetch로 CORS/무한응답 때문에 판정이 까다로움
   * - 그래서 <img src=".../mjpeg"> 로 첫 프레임 로딩을 시도하고,
   *   onload / onerror / timeout으로 간이 판정
   * - (브라우저/서버에 따라 onload가 애매할 수 있으니, "스트림 열기"가 최종 확인)
   */
  const checkStream = async () => {
    if (!streamUrl) return;

    const t0 = performance.now();
    setStreamCheck({ status: "checking", ms: null, error: "" });

    try {
      const ok = await new Promise((resolve, reject) => {
        const img = new Image();

        const timer = setTimeout(() => {
          cleanup();
          reject(new Error("timeout"));
        }, 1200);

        const cleanup = () => {
          clearTimeout(timer);
          img.onload = null;
          img.onerror = null;
        };

        img.onload = () => {
          cleanup();
          resolve(true);
        };
        img.onerror = () => {
          cleanup();
          reject(new Error("load failed"));
        };

        // 캐시 방지
        img.src = `${streamUrl}?t=${Date.now()}`;
      });

      const ms = Math.round(performance.now() - t0);
      setStreamCheck({ status: "ok", ms, error: "" });
      return ok;
    } catch (e) {
      const ms = Math.round(performance.now() - t0);
      setStreamCheck({
        status: "fail",
        ms,
        error: e?.message || "failed",
      });
      return false;
    }
  };

  if (!open) return null;

  const streamPill = (() => {
    if (!streamUrl) return <StatusPill>STREAM: -</StatusPill>;
    if (streamCheck.status === "checking") return <StatusPill>STREAM: CHECK…</StatusPill>;
    if (streamCheck.status === "ok")
      return <StatusPill tone="ok">STREAM: OK ({streamCheck.ms}ms)</StatusPill>;
    if (streamCheck.status === "fail")
      return (
        <StatusPill tone="bad" title={streamCheck.error || "fail"}>
          STREAM: FAIL ({streamCheck.ms}ms)
        </StatusPill>
      );
    return <StatusPill>STREAM: -</StatusPill>;
  })();

  return (
    <div
      className="fixed inset-0 z-[99999] flex items-center justify-center bg-black/60 px-4 py-6"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div
        className={cn(
          "w-full max-w-[720px] max-h-[85vh] overflow-auto",
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

            <div className="mt-2 flex items-center gap-2">
              {streamPill}
              <button
                type="button"
                onClick={checkStream}
                disabled={!streamUrl || streamCheck.status === "checking"}
                className={cn(
                  "px-3 py-1 rounded-xl text-[11px] font-semibold ring-1",
                  "transition-all duration-150",
                  (!streamUrl || streamCheck.status === "checking")
                    ? "opacity-60 cursor-not-allowed bg-base-100/20 ring-base-300/40"
                    : "bg-base-100/20 ring-base-300/50 hover:bg-base-100/45"
                )}
                title="스트림 접근을 간단히 점검"
              >
                {streamCheck.status === "checking" ? "점검 중..." : "스트림 점검"}
              </button>

              <button
                type="button"
                onClick={openStream}
                disabled={!streamUrl}
                className={cn(
                  "px-3 py-1 rounded-xl text-[11px] font-semibold ring-1",
                  "transition-all duration-150",
                  !streamUrl
                    ? "opacity-60 cursor-not-allowed bg-base-100/20 ring-base-300/40"
                    : "bg-base-100/20 ring-base-300/50 hover:bg-base-100/45"
                )}
                title="새 탭에서 스트림을 직접 열어 확인"
              >
                스트림 열기
              </button>
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
                <div className="text-right font-semibold break-all min-w-0">
                  {pairing?.pc || "-"}
                </div>

                <div className="opacity-70">HTTP</div>
                <div className="text-right font-semibold">
                  {pairing?.httpPort ?? "-"}
                </div>

                <div className="opacity-70">UDP</div>
                <div className="text-right font-semibold">
                  {pairing?.udpPort ?? "-"}
                </div>

                <div className="opacity-70">Name</div>
                <div className="text-right font-semibold break-all min-w-0">
                  {pairing?.name ?? "-"}
                </div>
              </div>

              {/* Buttons */}
              <div className="mt-5 flex flex-wrap gap-2">
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

                {/* Stream URL */}
                <div className="mt-3">
                  <div className="text-[11px] opacity-60 mb-1">스트림 URL</div>
                  <div
                    className={cn(
                      "text-[11px] opacity-70 break-all",
                      "rounded-xl ring-1 bg-base-100/20 ring-base-300/40",
                      "p-3"
                    )}
                  >
                    {streamUrl || "-"}
                  </div>
                  {streamCheck.status === "fail" && streamCheck.error ? (
                    <div className="mt-2 text-[11px] opacity-70">
                      오류: <span className="font-semibold">{streamCheck.error}</span>
                    </div>
                  ) : null}
                </div>

                {/* ✅ 배포용 안내 문구 */}
                <div className="mt-4 rounded-2xl ring-1 bg-base-100/18 ring-base-300/40 p-4">
                  <div className="text-xs font-semibold">연결 안내</div>
                  <ul className="mt-2 space-y-1 text-[11px] opacity-70 leading-relaxed list-disc pl-4">
                    <li>
                      PC와 휴대폰은 <b>같은 Wi-Fi(같은 네트워크)</b>에 연결되어야 합니다.
                    </li>
                    <li>
                      학원/회사 <b>게스트 Wi-Fi</b>는 단말 간 통신이 차단될 수 있습니다.
                    </li>
                    <li>
                      연결이 안 되면 <b>휴대폰 핫스팟에 PC를 연결</b>하는 방법이 가장 확실합니다.
                    </li>
                    <li>
                      원격(외부망) 연결은 <b>VPN(Tailscale 등) 설치</b>가 필요합니다.
                    </li>
                  </ul>
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
