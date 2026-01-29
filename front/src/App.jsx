import { useEffect, useMemo, useRef, useState } from "react";
import TitleBar from "./components/TitleBar";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import AgentHud from "./components/AgentHud";
import Rush3DPage from "./pages/Rush3DPage";
import PairingQrModal from "./components/PairingQrModal";
import TrainingLab from "./pages/TrainingLab";
import { THEME } from "./theme/themeTokens";
import { apiFetch } from "./api/http";

const VALID_THEMES = new Set(["dark", "light", "neon", "rose", "devil"]);

function cn(...xs) {
  return xs.filter(Boolean).join(" ");
}

export default function App() {
  const [hudOn, setHudOn] = useState(() => {
    const v = localStorage.getItem("hudOn");
    return v === null ? true : v === "1";
  });

  const [osHudOn, setOsHudOn] = useState(() => {
    const v = localStorage.getItem("osHudOn");
    return v === null ? true : v === "1";
  });

  useEffect(() => {
    if (!window.managerWin?.onDeepLink) return;

    const off = window.managerWin.onDeepLink(async (rawUrl) => {
      try {
        let code = null;

        try {
          const u = new URL(rawUrl);
          code = u.searchParams.get("code");
        } catch {
          const qs = rawUrl.split("?")[1] || "";
          code = new URLSearchParams(qs).get("code");
        }

        if (!code) return;

        const res = await apiFetch("/api/auth/bridge/consume", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          credentials: "include",
          body: JSON.stringify({ code }),
        });

        if (!res.ok) throw new Error(`consume failed: ${res.status}`);

        const data = await res.json();

        if (data?.accessToken) {
          localStorage.setItem("accessToken", data.accessToken);
        }

        window.location.reload();
      } catch (e) {
        console.error("deeplink auth failed:", e);
      }
    });

    return off;
  }, []);

  useEffect(() => {
    localStorage.setItem("hudOn", hudOn ? "1" : "0");
  }, [hudOn]);

  useEffect(() => {
    localStorage.setItem("osHudOn", osHudOn ? "1" : "0");
    apiFetch(`/api/hud/show?enabled=${osHudOn ? "true" : "false"}`, {
      method: "POST",
    }).catch(() => {});
  }, [osHudOn]);

  const toggleHud = () => setHudOn((x) => !x);
  const toggleOsHud = () => setOsHudOn((x) => !x);

  const [screen, setScreen] = useState("dashboard");
  const [hudFeed, setHudFeed] = useState(null);
  const hudActionsRef = useRef({});

  const [pairOpen, setPairOpen] = useState(false);
  const [pairing, setPairing] = useState(() => ({
    pc: "",
    httpPort: 8081,
    udpPort: 39500,
    name: "PC",
  }));

  const refreshPairing = () => {
    let cancelled = false;

    apiFetch("/api/pairing")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => {
        if (cancelled || !data) return;
        setPairing((prev) => ({ ...prev, ...data }));
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  };

  const savePairingName = async (nextName) => {
    const name = String(nextName || "").trim() || "PC";
    try {
      await apiFetch("/api/pairing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch {}
    refreshPairing();
  };

  const savePairingPc = async (nextPc) => {
    const pc = String(nextPc || "").trim();
    if (!pc) return;

    try {
      await apiFetch("/api/pairing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pc }),
      });
    } catch {}
    refreshPairing();
  };

  useEffect(() => {
    const cleanup = refreshPairing();
    return cleanup;
  }, []);

  const [theme, _setTheme] = useState(() => {
    const saved = localStorage.getItem("theme") || "dark";
    return VALID_THEMES.has(saved) ? saved : "dark";
  });

  const setTheme = (next) => {
    const v = String(next || "").trim();
    if (!VALID_THEMES.has(v)) return;
    _setTheme(v);
  };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  const t = THEME[theme] || THEME.dark;

  const agentStatus = useMemo(() => {
    return {
      connected: !!hudFeed?.connected,
      locked: !!hudFeed?.locked,
      mode: hudFeed?.mode ?? "DEFAULT",
      cameraPresent: hudFeed?.cameraPresent ?? null,
      modeText: hudFeed?.modeText ?? undefined,
    };
  }, [hudFeed]);

  return (
    <div
      data-theme={theme}
      className={cn(
        "w-[100dvw] h-[100dvh] flex flex-col overflow-hidden min-w-0 min-h-0 relative",
        t.page,
      )}
    >
      {/* background */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div
          className={cn(
            "absolute -top-40 -left-40 h-[520px] w-[520px] rounded-full blur-3xl",
            t.glow1,
          )}
        />
        <div
          className={cn(
            "absolute -bottom-52 -right-48 h-[560px] w-[560px] rounded-full blur-3xl",
            t.glow2,
          )}
        />
        <div className={cn("absolute inset-0 bg-[size:60px_60px]", t.grid)} />
      </div>

      {/* TitleBar */}
      <div className="relative z-30">
        <TitleBar
          hudOn={hudOn}
          onToggleHud={toggleHud}
          osHudOn={osHudOn}
          onToggleOsHud={toggleOsHud}
          screen={screen}
          onChangeScreen={setScreen}
          theme={theme}
          setTheme={setTheme}
          agentStatus={agentStatus}
          onOpenPairing={() => {
            refreshPairing();
            setPairOpen(true);
          }}
        />
      </div>

      {/* ✅ 핵심: HUD(오버레이)가 바닥을 덮어도 콘텐츠가 안 가려지게 main에 bottom padding */}
      <main
        className={cn(
          "relative z-10 flex-1 min-h-0 min-w-0 text-sm",
          screen === "rush" ? "overflow-hidden" : "overflow-auto",
          screen !== "rush" ? (hudOn ? "pb-28" : "pb-6") : "",
        )}
      >
        <div className={cn(screen === "dashboard" ? "block" : "hidden", "w-full min-w-0")}>
          <Dashboard
            hudOn={hudOn}
            onToggleHud={toggleHud}
            onHudState={setHudFeed}
            onHudActions={(actions) => {
              hudActionsRef.current = actions || {};
            }}
            theme={theme}
            onChangeScreen={setScreen}
          />
        </div>

        {screen === "rush" && (
          <Rush3DPage status={hudFeed?.status} connected={hudFeed?.connected ?? true} />
        )}
        {screen === "settings" && <Settings theme={theme} />}
        {screen === "train" && <TrainingLab theme={theme} />}
      </main>

      {/* overlays */}
      <div className="relative z-40">
        {hudOn && (
          <AgentHud
            status={hudFeed?.status}
            connected={hudFeed?.connected ?? true}
            modeOptions={hudFeed?.modeOptions}
            onSetMode={(m) => hudActionsRef.current.applyMode?.(m)}
            onEnableToggle={(next) =>
              next ? hudActionsRef.current.start?.() : hudActionsRef.current.stop?.()
            }
            onPreviewToggle={() => hudActionsRef.current.togglePreview?.()}
            onLockToggle={(nextLocked) => {
              if (hudActionsRef.current.setLock) return hudActionsRef.current.setLock(nextLocked);
              return hudActionsRef.current.lockToggle?.();
            }}
            onRequestHide={() => setHudOn(false)}
          />
        )}

        <PairingQrModal
          open={pairOpen}
          onClose={() => setPairOpen(false)}
          pairing={pairing}
          onSaveName={savePairingName}
          onSavePc={savePairingPc}
        />
      </div>
    </div>
  );
}
