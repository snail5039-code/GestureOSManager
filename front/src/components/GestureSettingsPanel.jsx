import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { THEME } from "../theme/themeTokens";

const api = axios.create({
  baseURL: "/api",
  timeout: 7000,
  headers: { Accept: "application/json" },
});

const GESTURES = ["NONE", "OPEN_PALM", "PINCH_INDEX", "V_SIGN", "FIST", "OTHER"];

const MODE_CONFIG = {
  MOUSE: {
    label: "마우스",
    groups: [
      {
        key: "CURSOR",
        label: "커서 손",
        desc: "커서 손(메인 손)의 제스처",
        actions: [
          { path: ["MOUSE", "MOVE"], label: "이동", help: "커서를 움직일 때" },
          { path: ["MOUSE", "CLICK_DRAG"], label: "클릭/드래그", help: "클릭 또는 드래그" },
          { path: ["MOUSE", "RIGHT_CLICK"], label: "우클릭", help: "오른쪽 버튼" },
          { path: ["MOUSE", "LOCK_TOGGLE"], label: "잠금 토글", help: "센터에서 오래 유지" },
        ],
      },
      {
        key: "OTHER",
        label: "보조 손",
        desc: "보조 손(반대 손)의 제스처",
        actions: [{ path: ["MOUSE", "SCROLL_HOLD"], label: "스크롤(홀드)", help: "보조 손을 쥐고 이동" }],
      },
    ],
  },

  KEYBOARD: {
    label: "키보드",
    groups: [
      {
        key: "BASE",
        label: "기본 레이어",
        desc: "화살표 키",
        actions: [
          { path: ["KEYBOARD", "BASE", "LEFT"], label: "←", help: "왼쪽" },
          { path: ["KEYBOARD", "BASE", "RIGHT"], label: "→", help: "오른쪽" },
          { path: ["KEYBOARD", "BASE", "UP"], label: "↑", help: "위" },
          { path: ["KEYBOARD", "BASE", "DOWN"], label: "↓", help: "아래" },
        ],
      },
      {
        key: "FN",
        label: "FN 레이어",
        desc: "보조 손 FN_HOLD 제스처를 잠깐 하면 활성화",
        actions: [
          { path: ["KEYBOARD", "FN", "BACKSPACE"], label: "Backspace", help: "지우기" },
          { path: ["KEYBOARD", "FN", "SPACE"], label: "Space", help: "띄어쓰기" },
          { path: ["KEYBOARD", "FN", "ENTER"], label: "Enter", help: "확인" },
          { path: ["KEYBOARD", "FN", "ESC"], label: "ESC", help: "취소" },
        ],
      },
    ],
    extras: [
      {
        path: ["KEYBOARD", "FN_HOLD"],
        label: "FN_HOLD (보조 손)",
        help: "이 제스처를 하면 FN 레이어가 잠깐 켜져요",
      },
    ],
  },

  PRESENTATION: {
    label: "PPT",
    groups: [
      {
        key: "NAV",
        label: "슬라이드 이동",
        desc: "기본 이동",
        actions: [
          { path: ["PRESENTATION", "NAV", "NEXT"], label: "다음", help: "→" },
          { path: ["PRESENTATION", "NAV", "PREV"], label: "이전", help: "←" },
        ],
      },
      {
        key: "INTERACT",
        label: "오브젝트 선택",
        desc: "보조 손 INTERACT_HOLD 제스처를 하면 활성화",
        actions: [
          { path: ["PRESENTATION", "INTERACT", "TAB"], label: "Tab", help: "다음 링크" },
          { path: ["PRESENTATION", "INTERACT", "SHIFT_TAB"], label: "Shift+Tab", help: "이전 링크" },
          { path: ["PRESENTATION", "INTERACT", "ACTIVATE"], label: "Enter", help: "선택" },
          { path: ["PRESENTATION", "INTERACT", "PLAY_PAUSE"], label: "Alt+P", help: "재생/일시정지" },
        ],
      },
    ],
    extras: [
      {
        path: ["PRESENTATION", "INTERACT_HOLD"],
        label: "INTERACT_HOLD (보조 손)",
        help: "이 제스처를 하면 오브젝트 선택 레이어가 잠깐 켜져요",
      },
    ],
    notes: ["고정: 양손 OPEN_PALM = 슬라이드쇼 시작(F5)", "고정: 양손 PINCH_INDEX = 슬라이드쇼 종료(ESC)"],
  },
};

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

function getIn(obj, path, fallback = "NONE") {
  let cur = obj;
  for (const p of path) {
    if (!cur || typeof cur !== "object") return fallback;
    cur = cur[p];
  }
  return typeof cur === "string" ? cur : fallback;
}

function setIn(obj, path, value) {
  const root = structuredClone(obj);
  let cur = root;
  for (let i = 0; i < path.length - 1; i++) {
    const k = path[i];
    if (!cur[k] || typeof cur[k] !== "object") cur[k] = {};
    cur = cur[k];
  }
  cur[path[path.length - 1]] = value;
  return root;
}

function Dialog({ open, title, children, actions, onClose }) {
  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[100000] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/45 backdrop-blur-sm"
        onMouseDown={onClose}
      />
      <div
        className={cn(
          "relative w-full max-w-lg",
          "rounded-xl ring-1 border border-base-300/60",
          "bg-base-200/92 text-base-content shadow-2xl",
          "backdrop-blur-md"
        )}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-base-300/45">
          <div className="text-sm font-semibold whitespace-nowrap">{title}</div>
        </div>

        <div className="px-5 py-4 text-sm">{children}</div>

        <div className="px-5 pb-4 flex items-center justify-end gap-2">
          {actions}
        </div>
      </div>
    </div>,
    document.body
  );
}

function SegBtn({ active, children, onClick, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "px-3 py-2 text-xs font-semibold transition",
        "rounded-md ring-1",
        active
          ? "bg-base-100/30 ring-base-300/70"
          : "bg-transparent ring-base-300/45 hover:bg-base-100/15"
      )}
    >
      <span className="whitespace-nowrap">{children}</span>
    </button>
  );
}

function ActionRow({ label, help, value, onChange, disabled }) {
  return (
    <div className="rounded-lg bg-base-100/10 ring-1 ring-base-300/45 px-4 py-3">
      <div className="grid grid-cols-[1fr_auto] items-center gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold whitespace-nowrap">{label}</div>
          <div className="text-[11px] opacity-70 truncate">{help}</div>
        </div>

        <select
          className="select select-sm select-bordered w-[170px]"
          value={value}
          onChange={onChange}
          disabled={disabled}
        >
          {GESTURES.map((gg) => (
            <option key={gg} value={gg}>
              {gg}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

export default function GestureSettingsPanel({ theme, embedded = false, onRequestClose }) {
  const t = THEME[theme] || THEME.dark;

  const [mode, setMode] = useState("MOUSE");
  const [settings, setSettings] = useState({ version: 1, bindings: {} });
  const bindings = settings && settings.bindings ? settings.bindings : {};

  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(null);
  const [result, setResult] = useState(null);

  const activeConf = MODE_CONFIG[mode];

  const load = async () => {
    setBusy(true);
    try {
      const { data } = await api.get("/settings");
      setSettings(data || { version: 1, bindings: {} });
    } catch (e) {
      setResult({ tone: "error", title: "불러오기 실패", text: "설정을 불러오지 못했어요. 서버 연결을 확인해 주세요." });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const body = { version: settings.version || 1, bindings: settings.bindings || {} };
      const { data } = await api.post("/settings", body);
      if (data && data.settings) setSettings(data.settings);

      setResult({
        tone: data && data.pushed ? "ok" : "warn",
        title: "저장 완료",
        text: data && data.pushed
          ? "저장한 설정이 에이전트에 적용됐어요."
          : "저장은 됐지만 에이전트 적용이 실패했어요. (연결 상태 확인)",
      });
    } catch (e) {
      setResult({ tone: "error", title: "저장 실패", text: "저장 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/settings/reset");
      if (data && data.settings) setSettings(data.settings);

      setResult({
        tone: data && data.pushed ? "ok" : "warn",
        title: "리셋 완료",
        text: data && data.pushed
          ? "기본값으로 리셋하고 에이전트에 적용했어요."
          : "리셋은 됐지만 에이전트 적용이 실패했어요. (연결 상태 확인)",
      });
    } catch (e) {
      setResult({ tone: "error", title: "리셋 실패", text: "리셋 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  };

  // 중복 체크는 같은 그룹 안에서만
  const groupGestureIndex = useMemo(() => {
    const idx = new Map();
    for (const g of activeConf.groups) {
      const map = new Map();
      for (const a of g.actions) {
        const v = getIn(bindings, a.path, "NONE");
        if (v && v !== "NONE") map.set(v, a.path.join("."));
      }
      idx.set(g.key, map);
    }
    return idx;
  }, [activeConf.groups, bindings]);

  const requestSet = (groupKey, path, next) => {
    const fullKey = path.join(".");
    const prev = getIn(bindings, path, "NONE");
    if (prev === next) return;

    const map = groupGestureIndex.get(groupKey);
    const conflictKey = next !== "NONE" ? (map ? map.get(next) : null) : null;
    if (conflictKey && conflictKey !== fullKey) {
      setConflict({ groupKey, path, prev, next, conflictKey });
      return;
    }

    setSettings((s) => ({
      ...s,
      bindings: setIn((s && s.bindings) || {}, path, next),
    }));
  };

  const resolveConflict = (action) => {
    if (!conflict) return;
    const { path, prev, next, conflictKey } = conflict;
    const conflictPath = conflictKey.split(".");

    if (action === "swap") {
      setSettings((s) => {
        let b = (s && s.bindings) || {};
        b = setIn(b, path, next);
        b = setIn(b, conflictPath, prev);
        return { ...s, bindings: b };
      });
    } else if (action === "replace") {
      setSettings((s) => {
        let b = (s && s.bindings) || {};
        b = setIn(b, conflictPath, "NONE");
        b = setIn(b, path, next);
        return { ...s, bindings: b };
      });
    }

    setConflict(null);
  };

  // ✅ embedded: 헤더/바디/푸터를 정확히 분리 (바디만 스크롤)
  const rootCls = embedded
    ? "h-full max-h-full flex flex-col"
    : "p-5 max-w-5xl mx-auto";

  const headerCls = embedded ? "px-4 pt-4" : "";
  const bodyCls = embedded ? "flex-1 min-h-0 overflow-auto px-4 pb-4" : "mt-4";
  const footerCls = embedded
    ? "px-4 py-3 border-t border-base-300/45 bg-base-200/80 backdrop-blur-md"
    : "mt-4";

  return (
    <div className={rootCls}>
      {/* Header */}
      <div className={cn(embedded ? headerCls : "")}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className={cn("font-semibold", embedded ? "text-base" : "text-xl")}>
              모션(제스처) 세팅
            </div>
            <div className={cn("opacity-70", embedded ? "text-[12px]" : "text-sm")}>
              액션별로 제스처를 바꿀 수 있어요
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              className={cn("btn btn-sm btn-ghost")}
              onClick={reset}
              disabled={busy}
              title="기본값으로 리셋"
            >
              리셋
            </button>

            {embedded && (
              <button
                className={cn("btn btn-sm btn-ghost")}
                onClick={() => onRequestClose && onRequestClose()}
                title="닫기"
                disabled={busy}
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Mode segmented */}
        <div className="mt-3 inline-flex items-center gap-2 rounded-lg ring-1 ring-base-300/45 bg-base-100/10 p-1">
          {Object.keys(MODE_CONFIG).map((m) => (
            <SegBtn key={m} active={mode === m} onClick={() => setMode(m)} disabled={busy}>
              {MODE_CONFIG[m].label}
            </SegBtn>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className={cn(bodyCls, embedded ? "mt-4" : "")}>
        {activeConf && activeConf.notes && activeConf.notes.length ? (
          <div className="rounded-xl ring-1 ring-base-300/45 bg-base-100/10 p-4 mb-4">
            <div className="text-sm font-semibold">참고</div>
            <ul className="list-disc pl-5 mt-2 text-[12px] opacity-80 space-y-1">
              {activeConf.notes.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <div className="grid gap-4">
          {activeConf.groups.map((g) => (
            <div
              key={g.key}
              className="rounded-xl border border-base-300/50 bg-base-200/35 p-4"
              style={{ boxShadow: t.glowShadowLite }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold whitespace-nowrap">{g.label}</div>
                  <div className="text-[12px] opacity-70 truncate">{g.desc}</div>
                </div>
              </div>

              <div className="mt-3 grid md:grid-cols-2 gap-3">
                {g.actions.map((a) => {
                  const v = getIn(bindings, a.path, "NONE");
                  return (
                    <ActionRow
                      key={a.path.join(".")}
                      label={a.label}
                      help={a.help}
                      value={v}
                      disabled={busy}
                      onChange={(e) => requestSet(g.key, a.path, e.target.value)}
                    />
                  );
                })}
              </div>
            </div>
          ))}

          {activeConf.extras && activeConf.extras.length ? (
            <div className="rounded-xl border border-base-300/50 bg-base-200/35 p-4">
              <div className="text-sm font-semibold">보조 설정</div>
              <div className="mt-3 grid md:grid-cols-2 gap-3">
                {activeConf.extras.map((x) => {
                  const v = getIn(bindings, x.path, "NONE");
                  return (
                    <ActionRow
                      key={x.path.join(".")}
                      label={x.label}
                      help={x.help}
                      value={v}
                      disabled={busy}
                      onChange={(e) => {
                        setSettings((s) => ({
                          ...s,
                          bindings: setIn((s && s.bindings) || {}, x.path, e.target.value),
                        }));
                      }}
                    />
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* Footer */}
      <div className={footerCls}>
        <div className="flex items-center justify-center">
          <button
            className={cn(
              "btn btn-primary",
              "h-10 min-h-0",
              "w-full max-w-[420px]"
            )}
            onClick={save}
            disabled={busy}
            title="저장하고 에이전트에 즉시 적용"
          >
            {busy ? "처리 중..." : "저장"}
          </button>
        </div>
      </div>

      {/* Conflict Dialog */}
      <Dialog
        open={!!conflict}
        title="중복 할당"
        onClose={() => setConflict(null)}
        actions={
          <>
            <button className="btn btn-sm" onClick={() => setConflict(null)}>
              Cancel
            </button>
            <button className="btn btn-sm btn-secondary" onClick={() => resolveConflict("swap")}>
              Swap
            </button>
            <button className="btn btn-sm btn-primary" onClick={() => resolveConflict("replace")}>
              Replace
            </button>
          </>
        }
      >
        <div className="text-[13px] opacity-85 leading-relaxed">
          같은 그룹 안에서 같은 제스처를 이미 쓰고 있어요.
          <div className="mt-2">
            {conflict ? (
              <>
                <span className="font-semibold">{conflict.next}</span> 는 이미
                <span className="font-semibold"> {conflict.conflictKey}</span> 에 할당돼 있어요.
                <div className="opacity-70 mt-1 text-[12px]">
                  Cancel: 변경 취소 / Swap: 서로 교체 / Replace: 기존을 NONE으로
                </div>
              </>
            ) : null}
          </div>
        </div>
      </Dialog>

      {/* Result Dialog */}
      <Dialog
        open={!!result}
        title={(result && result.title) || "완료"}
        onClose={() => setResult(null)}
        actions={
          <button
            className={cn(
              "btn btn-sm",
              result && result.tone === "ok"
                ? "btn-primary"
                : result && result.tone === "warn"
                ? "btn-secondary"
                : "btn-error"
            )}
            onClick={() => setResult(null)}
          >
            확인
          </button>
        }
      >
        <div className="text-[13px] opacity-85 whitespace-pre-line leading-relaxed">
          {(result && result.text) || ""}
        </div>
      </Dialog>
    </div>
  );
}
