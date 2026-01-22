import { useEffect, useMemo, useRef, useState, useCallback } from "react";

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function nowHHMM() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function mkId() {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }
}

function normalizeText(s) {
  return String(s || "")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .trim()
    .replace(/\s+/g, " ");
}

function inferOnOff(text) {
  const t = normalizeText(text);
  const lower = t.toLowerCase();

  if (
    /(켜|켜줘|on|enable|enabled|true)/.test(t) ||
    /(^|\s)on(\s|$)/.test(lower)
  )
    return true;
  if (
    /(꺼|꺼줘|off|disable|disabled|false)/.test(t) ||
    /(^|\s)off(\s|$)/.test(lower)
  )
    return false;

  return null;
}

function parseMode(text) {
  const t = normalizeText(text);
  const lower = t.toLowerCase();
  const hit = (re) => re.test(t) || re.test(lower);

  if (hit(/(마우스|mouse)/)) return "MOUSE";
  if (hit(/(키보드|keyboard)/)) return "KEYBOARD";
  if (hit(/(프레젠테이션|ppt|presentation)/)) return "PRESENTATION";
  if (hit(/(그리기|draw)/)) return "DRAW";
  if (hit(/(가상\s*키보드|vkey|virtual)/)) return "VKEY";
  return null;
}

const HELP_TEXT = [
  "사용 가능한 명령 예시",
  "- 시작해줘 / 정지해줘",
  "- 프리뷰 켜줘 / 프리뷰 꺼줘",
  "- 잠금 걸어줘 / 잠금 풀어줘",
  "- 모드 마우스 / 모드 키보드 / 모드 PPT / 모드 그리기 / 모드 가상키보드",
  "- 상태 보여줘",
  "- 가이드 (모션 가이드: JSON 연결 예정)",
  "",
  "참고",
  "- '감도'는 다음 단계에서 API 붙이면 바로 동작하게 연결 가능.",
].join("\n");

/**
 * DebugChat
 * - 메시지 영역(박스)은 고정 높이 + 내부 스크롤
 * - 상단 상태(연결됨/정지 등) 라인은 UI에서 제거
 * - 카메라 미연결 등 "버튼 클릭" 흐름에서도 채팅 로그를 찍기 위해
 *   window.__GOS_CHAT_LOG__("...") 전역 로거를 제공
 */
export default function DebugChat({
  t,
  busy,
  preview,
  derived,
  view,
  actions,
}) {
  const { start, stop, applyMode, togglePreview, setLock, fetchStatus } =
    actions || {};

  const [messages, setMessages] = useState(() => [
    {
      id: mkId(),
      role: "assistant",
      ts: nowHHMM(),
      text: "명령 채팅창 준비됨. 예: '시작해줘', '프리뷰 켜줘', '모드 키보드', '상태 보여줘'.\n'도움' 입력하면 목록을 보여줄게.",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const scrollBoxRef = useRef(null);
  const bottomRef = useRef(null);

  const pushMsg = useCallback((role, text) => {
    const msg = { id: mkId(), role, ts: nowHHMM(), text: String(text ?? "") };
    setMessages((prev) => [...prev, msg]);
  }, []);

  // ✅ Dashboard(버튼 클릭)에서도 채팅 로그를 찍고 싶으면:
  // window.__GOS_CHAT_LOG__?.("카메라 연결 후 사용 가능.")
  useEffect(() => {
    window.__GOS_CHAT_LOG__ = (text) => pushMsg("assistant", text);
    return () => {
      try {
        delete window.__GOS_CHAT_LOG__;
      } catch {
        // ignore
      }
    };
  }, [pushMsg]);

  // ✅ 새 메시지 추가될 때마다 하단으로 자동 스크롤 (박스 내부에서만)
  useEffect(() => {
    const bottom = bottomRef.current;
    if (!bottom) return;

    requestAnimationFrame(() => {
      try {
        bottom.scrollIntoView({ block: "end" });
      } catch {
        const box = scrollBoxRef.current;
        if (box) box.scrollTop = box.scrollHeight;
      }
    });
  }, [messages.length, sending]);

  // '상태 보여줘' 명령을 위한 텍스트(상단에 표시하진 않음)
  const statusLine = useMemo(() => {
    const conn = derived?.connected ? "연결됨" : "끊김";
    const en = derived?.enabled ? "실행 중" : "정지";
    const lock = derived?.locked ? "잠금" : "해제";
    const pv = preview ? "ON" : "OFF";
    const mode = view?.modeText || derived?.mode || "-";
    return `연결: ${conn} / 실행: ${en} / 잠금: ${lock} / Preview: ${pv} / 모드: ${mode}`;
  }, [
    derived?.connected,
    derived?.enabled,
    derived?.locked,
    derived?.mode,
    preview,
    view?.modeText,
  ]);

  const execCommand = async (raw) => {
    const text = normalizeText(raw);
    const lower = text.toLowerCase();

    if (!text) return "입력이 비었어. 예: '시작해줘'";

    if (/^(\?|help|도움)$/.test(lower) || text.includes("도움"))
      return HELP_TEXT;
    if (text.includes("상태") || lower.includes("status")) return statusLine;

    if (text.includes("가이드") || lower.includes("guide")) {
      return "모션 가이드 JSON은 연결 전이야. 다음 단계에서 JSON 붙이면 '가이드'로 모드별 가이드를 보여줄게.";
    }

    if (/(시작|start|실행)/.test(text)) {
      if (typeof start !== "function") return "start 액션이 연결되지 않았어.";

      const res = await start({ source: "chat" });
      if (res?.ok === false && res?.reason === "camera") {
        return res?.message || "카메라 연결 후 사용 가능.";
      }
      return "실행 요청 완료.";
    }

    if (/(정지|중지|stop)/.test(text)) {
      if (typeof stop !== "function") return "stop 액션이 연결되지 않았어.";
      await stop();
      return "정지 요청 완료.";
    }

    if (text.includes("프리뷰") || lower.includes("preview")) {
      if (typeof togglePreview !== "function")
        return "preview 액션이 연결되지 않았어.";

      const want = inferOnOff(text);
      const res = await togglePreview(want, { source: "chat" });

      if (res?.ok === false && res?.reason === "camera") {
        return res?.message || "카메라 연결 후 Preview 사용 가능.";
      }

      if (want === null) return "Preview 토글 완료.";
      return want ? "Preview ON 완료." : "Preview OFF 완료.";
    }

    if (
      text.includes("잠금") ||
      text.includes("락") ||
      lower.includes("lock")
    ) {
      if (typeof setLock !== "function") return "lock 액션이 연결되지 않았어.";

      const want = (() => {
        if (/(풀|해제)/.test(text)) return false;
        const v = inferOnOff(text);
        if (v !== null) return v;
        return !derived?.locked;
      })();

      await setLock(!!want);
      return want ? "잠금 ON 완료." : "잠금 해제 완료.";
    }

    if (text.includes("모드") || lower.includes("mode")) {
      if (typeof applyMode !== "function")
        return "mode 액션이 연결되지 않았어.";

      const m = parseMode(text);
      if (!m)
        return "모드를 못 찾겠어. 예: '모드 마우스', '모드 키보드', '모드 PPT'";

      const res = await applyMode(m, { source: "chat" });
      if (res?.ok === false && res?.reason === "camera") {
        return res?.message || "카메라 연결 후 모드 변경 가능.";
      }

      return `모드 변경 완료: ${m}`;
    }

    if (
      text.includes("감도") ||
      text.includes("민감") ||
      lower.includes("sensitivity")
    ) {
      return "감도(포인터 속도/민감도) 조절은 다음 단계에서 API를 붙여서 동작하게 만들자.";
    }

    return "명령을 이해 못했어. '도움'을 입력하면 가능한 명령 목록을 보여줄게.";
  };

  const onSend = async () => {
    const text = normalizeText(input);
    if (!text) return;

    pushMsg("user", text);
    setInput("");

    setSending(true);
    try {
      const out = await execCommand(text);
      pushMsg("assistant", out);

      if (typeof fetchStatus === "function") {
        try {
          await fetchStatus();
        } catch {
          // ignore
        }
      }
    } catch (e) {
      pushMsg("assistant", `오류: ${e?.message || String(e)}`);
    } finally {
      setSending(false);
    }
  };

  const disabled = !!busy || !!sending;

  const panel = t?.panelSoft || t?.panel2 || t?.panel;
  const botBubble = cn("ring-1", t?.panel2 || t?.panelSoft || t?.panel);
  const userBubble = "bg-sky-500/10 ring-sky-400/25";

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      {/* ✅ 상단 상태 라인 제거 (요청사항) */}

      {/* ✅ 메시지 박스는 고정 높이, 내부만 스크롤 */}
      <div
        ref={scrollBoxRef}
        className={cn(
          "flex-1 min-h-0 overflow-auto rounded-xl ring-1 p-3",
          panel,
          "overscroll-contain",
        )}
      >
        <div className="space-y-2">
          {messages.map((m) => {
            const isUser = m.role === "user";
            return (
              <div
                key={m.id}
                className={cn(
                  "w-full flex",
                  isUser ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[92%] md:max-w-[78%] px-3 py-2 rounded-xl ring-1",
                    isUser ? userBubble : botBubble,
                  )}
                >
                  <div
                    className={cn(
                      "whitespace-pre-wrap text-xs leading-relaxed",
                      t?.text,
                    )}
                  >
                    {m.text}
                  </div>
                  <div className={cn("mt-1 text-[10px] opacity-60", t?.muted)}>
                    {isUser ? "You" : "Agent"} · {m.ts}
                  </div>
                </div>
              </div>
            );
          })}

          {sending ? (
            <div className="w-full flex justify-start">
              <div
                className={cn(
                  "max-w-[78%] px-3 py-2 rounded-xl ring-1",
                  botBubble,
                )}
              >
                <div className={cn("text-xs opacity-70", t?.muted)}>
                  처리 중…
                </div>
              </div>
            </div>
          ) : null}

          <div ref={bottomRef} />
        </div>
      </div>

      <div className="grid grid-cols-[1fr_auto] gap-2">
        <input
          className={cn(
            "h-10 px-3 text-sm outline-none ring-1 rounded-xl transition disabled:opacity-50",
            t?.input,
          )}
          placeholder="명령 입력… (예: 시작해줘)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!disabled) onSend();
            }
          }}
          disabled={disabled}
        />

        <button
          type="button"
          onClick={onSend}
          disabled={disabled}
          className={cn(
            "h-10 px-4 text-sm font-semibold ring-1 rounded-xl transition disabled:opacity-50",
            t?.btn,
          )}
        >
          보내기
        </button>
      </div>

      <div className={cn("text-[11px] opacity-70", t?.muted)}>
        Enter로 전송, '도움'으로 명령 목록.
      </div>
    </div>
  );
}
