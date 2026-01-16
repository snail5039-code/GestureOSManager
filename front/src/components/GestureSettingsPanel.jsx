import axios from "axios";
import { useEffect, useMemo, useState } from "react";
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

/**
 * GestureSettingsPanel
 * - embedded=true  : 팝오버/모달 등에 넣기 좋은 컴팩트 레이아웃
 * - embedded=false : 기존 Settings 페이지용 레이아웃
 */
export default function GestureSettingsPanel({ theme, embedded = false, onRequestClose }) {
  const t = THEME[theme] || THEME.dark;
  const [mode, setMode] = useState("MOUSE");
  const [settings, setSettings] = useState({ version: 1, bindings: {} });
  const bindings = settings?.bindings || {};

  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(null);

  // ✅ 저장/리셋 결과 모달
  const [result, setResult] = useState(null); // { tone:'ok'|'warn'|'error', title, text }

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

  const activeConf = MODE_CONFIG[mode];

  const groupGestureIndex = useMemo(() => {
    // 중복 체크는 '같은 그룹' 안에서만
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
    const conflictKey = next !== "NONE" ? map?.get(next) : null;
    if (conflictKey && conflictKey !== fullKey) {
      setConflict({ groupKey, path, prev, next, conflictKey });
      return;
    }

    setSettings((s) => ({
      ...s,
      bindings: setIn(s.bindings || {}, path, next),
    }));
  };

  const resolveConflict = (action) => {
    if (!conflict) return;
    const { path, prev, next, conflictKey } = conflict;
    const conflictPath = conflictKey.split(".");

    if (action === "swap") {
      setSettings((s) => {
        let b = s.bindings || {};
        b = setIn(b, path, next);
        b = setIn(b, conflictPath, prev);
        return { ...s, bindings: b };
      });
    } else if (action === "replace") {
      setSettings((s) => {
        let b = s.bindings || {};
        b = setIn(b, conflictPath, "NONE");
        b = setIn(b, path, next);
        return { ...s, bindings: b };
      });
    }

    setConflict(null);
  };

  const save = async () => {
    setBusy(true);
    try {
      const body = { version: settings.version || 1, bindings: settings.bindings || {} };
      const { data } = await api.post("/settings", body);
      if (data?.settings) setSettings(data.settings);

      setResult({
        tone: data?.pushed ? "ok" : "warn",
        title: "저장 완료",
        text: data?.pushed
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
      if (data?.settings) setSettings(data.settings);

      setResult({
        tone: data?.pushed ? "ok" : "warn",
        title: "리셋 완료",
        text: data?.pushed
          ? "기본값으로 리셋하고 에이전트에 적용했어요."
          : "리셋은 됐지만 에이전트 적용이 실패했어요. (연결 상태 확인)",
      });
    } catch (e) {
      setResult({ tone: "error", title: "리셋 실패", text: "리셋 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  };

  // ✅ 레이아웃: embedded일 때는 “본문 스크롤 + 하단 고정 버튼”
  const rootCls = embedded ? "p-3 h-[80vh] max-h-[80vh] flex flex-col" : "p-5 max-w-5xl mx-auto";
  const bodyScrollCls = embedded ? "flex-1 overflow-auto pr-1" : "";

  return (
    <div className={rootCls}>
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={cn(embedded ? "text-lg" : "text-xl", "font-semibold")}>모션(제스처) 세팅</div>
          <div className={cn("text-sm opacity-70", embedded && "text-[12px]")}>
            액션별로 제스처를 바꿀 수 있어요. 중복이면 경고가 떠요.
          </div>
        </div>

        <div className="flex items-center gap-2">
          {embedded && (
            <button
              className={cn("btn btn-sm btn-ghost")}
              onClick={() => onRequestClose?.()}
              title="닫기 (ESC)"
              disabled={busy}
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Mode tabs */}
      <div className="mt-4 flex items-center gap-2 flex-wrap">
        {Object.keys(MODE_CONFIG).map((m) => (
          <button
            key={m}
            className={cn("btn btn-sm", mode === m ? "btn-secondary" : "btn-ghost")}
            onClick={() => setMode(m)}
            disabled={busy}
          >
            {MODE_CONFIG[m].label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className={cn("mt-4 grid gap-4", bodyScrollCls)}>
        {activeConf?.notes?.length ? (
          <div className="alert">
            <div>
              <div className="font-semibold">참고</div>
              <ul className={cn("list-disc pl-5 text-sm opacity-80", embedded && "text-[12px]")}>
                {activeConf.notes.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}

        {activeConf.groups.map((g) => (
          <div
            key={g.key}
            className="rounded-2xl border border-base-300 bg-base-200/40 p-4"
            style={{ boxShadow: t.glowShadowLite }}
          >
            <div>
              <div className="font-semibold">{g.label}</div>
              <div className={cn("text-sm opacity-70", embedded && "text-[12px]")}>{g.desc}</div>
            </div>

            <div className="mt-3 grid md:grid-cols-2 gap-3">
              {g.actions.map((a) => {
                const v = getIn(bindings, a.path, "NONE");
                return (
                  <div key={a.path.join(".")} className="rounded-xl bg-base-100/50 border border-base-300 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium">{a.label}</div>
                        <div className={cn("text-xs opacity-60", embedded && "text-[11px]")}>{a.help}</div>
                      </div>

                      <select
                        className="select select-sm select-bordered"
                        value={v}
                        onChange={(e) => requestSet(g.key, a.path, e.target.value)}
                        disabled={busy}
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
              })}
            </div>
          </div>
        ))}

        {activeConf.extras?.length ? (
          <div className="rounded-2xl border border-base-300 bg-base-200/40 p-4">
            <div className="font-semibold">보조 설정</div>
            <div className="mt-3 grid md:grid-cols-2 gap-3">
              {activeConf.extras.map((x) => {
                const v = getIn(bindings, x.path, "NONE");
                return (
                  <div key={x.path.join(".")} className="rounded-xl bg-base-100/50 border border-base-300 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-medium">{x.label}</div>
                        <div className={cn("text-xs opacity-60", embedded && "text-[11px]")}>{x.help}</div>
                      </div>
                      <select
                        className="select select-sm select-bordered"
                        value={v}
                        onChange={(e) => {
                          setSettings((s) => ({
                            ...s,
                            bindings: setIn(s.bindings || {}, x.path, e.target.value),
                          }));
                        }}
                        disabled={busy}
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
              })}
            </div>
          </div>
        ) : null}

        {/* embedded에서 footer가 가려지지 않게 여백 */}
        {embedded ? <div className="h-3" /> : null}
      </div>

      {/* ✅ Footer: 큰 저장 버튼 (항상 하단) */}
      <div
        className={cn(
          "mt-4",
          embedded &&
            "border-t border-base-300/60 bg-base-200/80 backdrop-blur " +
              "pt-3 pb-3 -mx-3 px-3"
        )}
      >
        <div className="flex items-center gap-2">
          <button className={cn("btn", "border border-base-300/70 bg-base-100/30 hover:bg-base-100/45")} onClick={reset} disabled={busy}>
            리셋
          </button>

          <button
            className={cn("btn btn-primary btn-lg flex-1")}
            onClick={save}
            disabled={busy}
            title="저장하고 에이전트에 즉시 적용"
          >
            {busy ? "처리 중..." : "저장 + 적용"}
          </button>
        </div>
        <div className="mt-1 text-[11px] opacity-60">저장하면 설정이 즉시 에이전트에 반영돼요.</div>
      </div>

      {/* conflict modal */}
      <input type="checkbox" className="modal-toggle" checked={!!conflict} onChange={() => setConflict(null)} />
      <div className="modal">
        <div className="modal-box">
          <h3 className="font-bold text-lg">중복 할당</h3>
          <p className="py-2 text-sm opacity-80">
            같은 그룹 안에서 같은 제스처를 이미 쓰고 있어요.
            <br />
            어떻게 처리할까요?
          </p>

          {conflict && (
            <div className="text-sm opacity-80">
              <div>
                <span className="font-semibold">{conflict.next}</span> 는 이미
                <span className="font-semibold"> {conflict.conflictKey}</span> 에 할당돼 있어요.
              </div>
              <div className="opacity-70 mt-1">(Cancel: 변경 취소 / Swap: 서로 교체 / Replace: 기존을 NONE으로)</div>
            </div>
          )}

          <div className="modal-action">
            <button className="btn" onClick={() => setConflict(null)}>
              Cancel
            </button>
            <button className="btn btn-secondary" onClick={() => resolveConflict("swap")}>
              Swap
            </button>
            <button className="btn btn-primary" onClick={() => resolveConflict("replace")}>
              Replace
            </button>
          </div>
        </div>
      </div>

      {/* ✅ result modal (저장/리셋 완료 창) */}
      <input type="checkbox" className="modal-toggle" checked={!!result} onChange={() => setResult(null)} />
      <div className="modal">
        <div className="modal-box">
          <h3 className="font-bold text-lg">{result?.title ?? "완료"}</h3>
          <p className="py-3 text-sm opacity-80 whitespace-pre-line">{result?.text ?? ""}</p>

          <div className="modal-action">
            <button
              className={cn(
                "btn",
                result?.tone === "ok" ? "btn-primary" : result?.tone === "warn" ? "btn-secondary" : "btn-error"
              )}
              onClick={() => setResult(null)}
            >
              확인
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
