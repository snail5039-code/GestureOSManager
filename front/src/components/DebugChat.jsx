// src/components/DebugChat.jsx
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

  if (/(켜|켜줘|on|enable|enabled|true)/.test(t) || /(^|\s)on(\s|$)/.test(lower)) return true;
  if (/(꺼|꺼줘|off|disable|disabled|false)/.test(t) || /(^|\s)off(\s|$)/.test(lower)) return false;

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

function parseGainFromText(text) {
  const m = String(text).match(/-?\d+(\.\d+)?/);
  if (!m) return null;
  const v = Number(m[0]);
  return Number.isFinite(v) ? v : null;
}

const HELP_TEXT = [
  "사용 가능한 명령 예시",
  "- 시작해줘 / 정지해줘",
  "- 프리뷰 켜줘 / 프리뷰 꺼줘",
  "- 잠금 걸어줘 / 잠금 풀어줘",
  "- 모드 마우스 / 모드 키보드 / 모드 PPT / 모드 그리기 / 모드 가상키보드",
  "- 감도 1.6 (0.2 ~ 4.0)",
  "- 상태 보여줘",
  "- (그 외 질문은 AI가 자연스럽게 대화함. 예: '모션 기능 뭐있어', '우 클릭은?', '안녕')",
].join("\n");

async function callAi(message) {
  const r = await fetch("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ message }),
  });

  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.ok === false) throw new Error(j.error || "AI 호출 실패");
  return {
    text: String(j.text || "").trim(),
    cards: Array.isArray(j.cards) ? j.cards : [],
    meta: j.meta || {},
  };
}

function groupCardsByMode(cards) {
  const map = new Map();
  for (const c of cards || []) {
    const mode = String(c.mode || "etc");
    if (!map.has(mode)) map.set(mode, []);
    map.get(mode).push(c);
  }
  return Array.from(map.entries());
}

export default function DebugChat({ t, busy, preview, derived, view, actions }) {
  const { start, stop, applyMode, togglePreview, setLock, fetchStatus, setGain } = actions || {};

  const [messages, setMessages] = useState(() => [
    {
      id: mkId(),
      role: "assistant",
      ts: nowHHMM(),
      text:
        "명령 채팅창 준비됨.\n" +
        "예: '시작해줘', '프리뷰 켜줘', '모드 키보드', '감도 1.6', '상태 보여줘'\n" +
        "또는 자연스럽게 질문해도 돼. 예: '모션 기능 뭐있어', '우 클릭은?', '안녕'\n" +
        "'도움' 입력하면 목록을 보여줄게.",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  // ✅ “모드별 더보기” 펼침 상태: key = `${messageId}:${mode}`
  const [expanded, setExpanded] = useState({});

  const scrollBoxRef = useRef(null);
  const bottomRef = useRef(null);

  const pushMsg = useCallback((role, text, extra) => {
    const msg = { id: mkId(), role, ts: nowHHMM(), text: String(text ?? ""), ...(extra || {}) };
    setMessages((prev) => [...prev, msg]);
  }, []);

  useEffect(() => {
    window.__GOS_CHAT_LOG__ = (...args) => {
      if (args.length === 1) {
        pushMsg("agent", args[0]);
        return;
      }
      const [role, text] = args;

      const r = String(role || "agent").toLowerCase();
      const mapped = r === "user" ? "user" : r === "assistant" || r === "system" ? "assistant" : "agent";

      pushMsg(mapped, text);
    };

    return () => {
      try {
        delete window.__GOS_CHAT_LOG__;
      } catch {
        // ignore
      }
    };
  }, [pushMsg]);

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

  const statusLine = useMemo(() => {
    const conn = derived?.connected ? "연결됨" : "끊김";
    const en = derived?.enabled ? "실행 중" : "정지";
    const lock = derived?.locked ? "잠금" : "해제";
    const pv = preview ? "ON" : "OFF";
    const mode = view?.modeText || derived?.mode || "-";
    return `연결: ${conn} / 실행: ${en} / 잠금: ${lock} / Preview: ${pv} / 모드: ${mode}`;
  }, [derived?.connected, derived?.enabled, derived?.locked, derived?.mode, preview, view?.modeText]);

  const execCommand = async (raw) => {
    const text = normalizeText(raw);
    const lower = text.toLowerCase();

    if (!text) return "입력이 비었어. 예: '시작해줘'";

    if (/^(\?|help|도움)$/.test(lower) || text.includes("도움")) return HELP_TEXT;
    if (text.includes("상태") || lower.includes("status")) return statusLine;

    // --- 로컬 명령 우선 처리 ---
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
      if (typeof togglePreview !== "function") return "preview 액션이 연결되지 않았어.";

      const want = inferOnOff(text);
      const res = await togglePreview(want, { source: "chat" });

      if (res?.ok === false && res?.reason === "camera") {
        return res?.message || "카메라 연결 후 Preview 사용 가능.";
      }

      if (want === null) return "Preview 토글 완료.";
      return want ? "Preview ON 완료." : "Preview OFF 완료.";
    }

    if (text.includes("잠금") || text.includes("락") || lower.includes("lock")) {
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
      if (typeof applyMode !== "function") return "mode 액션이 연결되지 않았어.";

      const m = parseMode(text);
      if (!m) return "모드를 못 찾겠어. 예: '모드 마우스', '모드 키보드', '모드 PPT'";

      const res = await applyMode(m, { source: "chat" });
      if (res?.ok === false && res?.reason === "camera") {
        return res?.message || "카메라 연결 후 모드 변경 가능.";
      }

      return `모드 변경 완료: ${m}`;
    }

    if (text.includes("감도") || text.includes("민감") || lower.includes("sensitivity") || lower.includes("gain")) {
      if (typeof setGain !== "function") return "setGain 액션이 연결되지 않았어.";

      const v = parseGainFromText(text);
      if (v === null) return "감도 값(0.2~4.0)을 같이 적어줘. 예: 감도 1.6";

      const res = await setGain(v);
      if (res?.ok) return `감도 적용 완료: ${Number(res.gain).toFixed(2)} (허용 범위 0.2~4.0)`;
      return res?.message || "감도 변경 실패";
    }

    // --- 그 외: 전부 AI로 (백엔드가 “가이드 질문 vs 일반 대화”를 알아서 분기함) ---
    return await callAi(text);
  };

  const onSend = async () => {
    const text = normalizeText(input);
    if (!text) return;

    pushMsg("user", text);
    setInput("");

    setSending(true);
    try {
      const out = await execCommand(text);

      if (typeof out === "object" && out && "text" in out) {
        pushMsg("assistant", out.text, { cards: out.cards || [], meta: out.meta || {} });
      } else {
        pushMsg("assistant", out);
      }

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

  const toggleMore = (messageId, mode) => {
    const k = `${messageId}:${mode}`;
    setExpanded((prev) => ({ ...prev, [k]: !prev[k] }));
  };

  const modeLabel = (m) => {
    const s = String(m || "").toLowerCase();
    if (s === "mouse") return "마우스";
    if (s === "keyboard") return "키보드";
    if (s === "draw") return "그리기";
    if (s === "presentation") return "PPT";
    if (s === "vkey") return "가상키보드";
    return m || "기타";
  };

  return (
    <div className="h-full min-h-0 flex flex-col gap-3">
      <div
        ref={scrollBoxRef}
        className={cn("flex-1 min-h-0 overflow-auto rounded-xl ring-1 p-3", panel, "overscroll-contain")}
      >
        <div className="space-y-2">
          {messages.map((m) => {
            const isUser = m.role === "user";
            const hasCards = !isUser && Array.isArray(m.cards) && m.cards.length > 0;

            return (
              <div key={m.id} className={cn("w-full flex", isUser ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[92%] md:max-w-[78%] px-3 py-2 rounded-xl ring-1",
                    isUser ? userBubble : botBubble
                  )}
                >
                  <div className={cn("whitespace-pre-wrap text-xs leading-relaxed", t?.text)}>{m.text}</div>

                  {hasCards ? (
                    <div className="mt-2 space-y-3">
                      {groupCardsByMode(m.cards).map(([mode, list]) => {
                        const label = modeLabel(mode);
                        const key = `${m.id}:${mode}`;
                        const isOpen = !!expanded[key];
                        const show = isOpen ? list : list.slice(0, 3);
                        const hiddenCount = Math.max(0, list.length - show.length);

                        return (
                          <div key={key} className={cn("rounded-xl ring-1 p-2", t?.panel2 || t?.panelSoft || t?.panel)}>
                            <div className={cn("text-[11px] font-semibold", t?.text)}>
                              {label} ({list.length})
                            </div>

                            <div className="mt-2 space-y-2">
                              {show.map((c, idx) => (
                                <div key={idx} className={cn("rounded-xl ring-1 p-2", t?.panel2 || t?.panelSoft || t?.panel)}>
                                  <div className={cn("text-xs font-semibold", t?.text)}>{c.title}</div>

                                  <div className={cn("mt-1 text-[11px] opacity-80", t?.muted)}>
                                    {c.trigger ? `trigger: ${c.trigger}` : ""}
                                    {c.action ? ` · action: ${c.action}` : ""}
                                  </div>

                                  {c.image ? (
                                    <img
                                      src={c.image}
                                      alt={c.title}
                                      className="mt-2 w-full max-w-[320px] rounded-lg ring-1 block object-contain"
                                      loading="lazy"
                                    />
                                  ) : null}

                                  {Array.isArray(c.howTo) && c.howTo.length ? (
                                    <ul className={cn("mt-2 text-[11px] list-disc pl-5", t?.text)}>
                                      {c.howTo.map((s, i) => (
                                        <li key={i}>{s}</li>
                                      ))}
                                    </ul>
                                  ) : null}
                                </div>
                              ))}
                            </div>

                            {hiddenCount > 0 ? (
                              <button
                                type="button"
                                className={cn("mt-2 text-[11px] underline opacity-80", t?.text)}
                                onClick={() => toggleMore(m.id, mode)}
                              >
                                더보기 (+{hiddenCount})
                              </button>
                            ) : list.length > 3 ? (
                              <button
                                type="button"
                                className={cn("mt-2 text-[11px] underline opacity-80", t?.text)}
                                onClick={() => toggleMore(m.id, mode)}
                              >
                                접기
                              </button>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  <div className={cn("mt-2 text-[10px] opacity-60", t?.muted)}>
                    {isUser ? "You" : "Agent"} · {m.ts}
                  </div>
                </div>
              </div>
            );
          })}

          {sending ? (
            <div className="w-full flex justify-start">
              <div className={cn("max-w-[78%] px-3 py-2 rounded-xl ring-1", botBubble)}>
                <div className={cn("text-xs opacity-70", t?.muted)}>처리 중…</div>
              </div>
            </div>
          ) : null}

          <div ref={bottomRef} />
        </div>
      </div>

      <div className="grid grid-cols-[1fr_auto] gap-2">
        <input
          className={cn("h-10 px-3 text-sm outline-none ring-1 rounded-xl transition disabled:opacity-50", t?.input)}
          placeholder="명령 입력… (예: 시작해줘 / 감도 1.6)"
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
          className={cn("h-10 px-4 text-sm font-semibold ring-1 rounded-xl transition disabled:opacity-50", t?.btn)}
        >
          보내기
        </button>
      </div>
    </div>
  );
}
