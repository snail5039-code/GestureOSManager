const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const net = require("net");

const ICON_PNG_PATH = path.join(__dirname, "assets", "icon.png");

let win;
const DEV_URL = "http://localhost:5173";
const PROTOCOL = "gestureos";

// ===============================
// Agent (Python Overlay) start/stop
// ===============================
let agentProc = null;
let agentStartScheduled = false;
let quitting = false;

const PID_FILE = path.join(app.getPath("userData"), "gestureos-agent.pid");
const AGENT_LOG = path.join(app.getPath("userData"), "agent.log");

function logLine(...xs) {
  try {
    const line = `[${new Date().toISOString()}] ${xs.map(String).join(" ")}\n`;
    fs.appendFileSync(AGENT_LOG, line, "utf-8");
  } catch {}
}

function getExtraResourcesRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "resources")
    : path.join(__dirname, "..", "resources");
}


// ===============================
// Backend (Spring Control API) start/stop (8080)
// - 설치본(로컬)에서 WS/Control API가 안 붙는 가장 큰 원인: 8080 백엔드가 안 떠있음
// - resources/backend/*.jar 을 자동으로 올려서 실행한다.
// ===============================
let backendProc = null;
let backendStartScheduled = false;

const BACKEND_PORT = 8080;
const BACKEND_PID_FILE = path.join(app.getPath("userData"), "gestureos-backend.pid");
const BACKEND_LOG = path.join(app.getPath("userData"), "backend.log");

function logBackend(...xs) {
  try {
    const line = `[${new Date().toISOString()}] ${xs.map(String).join(" ")}
`;
    fs.appendFileSync(BACKEND_LOG, line, "utf-8");
  } catch {}
}

function isPortOpen(port, host = "127.0.0.1", timeoutMs = 250) {
  return new Promise((resolve) => {
    try {
      const sock = new net.Socket();
      let done = false;
      const finish = (ok) => {
        if (done) return;
        done = true;
        try { sock.destroy(); } catch {}
        resolve(!!ok);
      };
      sock.setTimeout(timeoutMs);
      sock.once("connect", () => finish(true));
      sock.once("timeout", () => finish(false));
      sock.once("error", () => finish(false));
      sock.connect(port, host);
    } catch {
      resolve(false);
    }
  });
}

function findBackendJar(root) {
  try {
    const dir = path.join(root, "backend");
    if (!fs.existsSync(dir)) return null;

    // 우선 고정 이름(권장)
    const fixed = path.join(dir, "gestureos-manager.jar");
    if (fs.existsSync(fixed)) return fixed;

    // 아니면 폴더에서 가장 그럴듯한 jar 1개 선택
    const jars = fs
      .readdirSync(dir)
      .filter((f) => f.toLowerCase().endsWith(".jar"))
      .map((f) => path.join(dir, f));

    if (!jars.length) return null;

    jars.sort((a, b) => a.length - b.length);
    return jars[0];
  } catch {
    return null;
  }
}

function resolveJavaCmd(root) {
  // (선택) 번들 JRE가 있으면 우선 사용
  try {
    const jreWin = path.join(root, "jre", "bin", "javaw.exe");
    if (process.platform === "win32" && fs.existsSync(jreWin)) return jreWin;

    const jreNix = path.join(root, "jre", "bin", "java");
    if (process.platform !== "win32" && fs.existsSync(jreNix)) return jreNix;
  } catch {}

  // 시스템 Java 사용
  return process.platform === "win32" ? "javaw" : "java";
}

async function startBackendNow() {
  try {
    const already = await isPortOpen(BACKEND_PORT);
    if (already) {
      logBackend("[backend] already up on", BACKEND_PORT);
      return;
    }

    // 중복 실행 방지
    if (backendProc) return;

    const root = getExtraResourcesRoot();
    const jarPath = findBackendJar(root);

    logBackend("[backend] try start. jarPath=", jarPath);

    if (!jarPath || !fs.existsSync(jarPath)) {
      logBackend("[backend] NOT FOUND. put jar under resources/backend/*.jar");
      return;
    }

    const javaCmd = resolveJavaCmd(root);
    const out = fs.openSync(BACKEND_LOG, "a");

    // Spring Boot: --server.port 로 강제(설치본 충돌 방지)
    backendProc = spawn(javaCmd, ["-jar", jarPath, `--server.port=${BACKEND_PORT}`], {
      cwd: path.dirname(jarPath),
      detached: true,
      windowsHide: true,
      stdio: ["ignore", out, out],
    });

    logBackend("[backend] started pid=", backendProc.pid);

    try { fs.writeFileSync(BACKEND_PID_FILE, String(backendProc.pid), "utf-8"); } catch {}

    backendProc.on("exit", (code, signal) => {
      logBackend("[backend] exit code=", code, "signal=", signal);
    });
    backendProc.on("error", (err) => {
      logBackend("[backend] spawn error:", err?.message || err);
    });

    backendProc.unref();

    // 포트가 실제로 열릴 때까지 조금 기다려서(최대 10초) WS 초반 실패를 줄임
    for (let i = 0; i < 40; i++) {
      const ok = await isPortOpen(BACKEND_PORT);
      if (ok) {
        logBackend("[backend] ready on", BACKEND_PORT);
        break;
      }
      await new Promise((r) => setTimeout(r, 250));
    }
  } catch (e) {
    logBackend("[backend] start exception:", e?.message || e);
  }
}

function startBackendAfterRendererReady() {
  if (backendStartScheduled) return;
  backendStartScheduled = true;

  win.webContents.once("did-finish-load", () => {
    logBackend("[backend] renderer did-finish-load → start backend");
    setTimeout(() => startBackendNow(), 50);
  });

  setTimeout(() => startBackendNow(), 500);
}

function stopBackend() {
  try {
    let pid = null;

    try {
      if (fs.existsSync(BACKEND_PID_FILE)) {
        pid = parseInt(fs.readFileSync(BACKEND_PID_FILE, "utf-8"), 10);
      }
    } catch {}

    if (!pid) {
      try { pid = backendProc?.pid || null; } catch {}
    }

    if (pid) {
      logBackend("[backend] stop pid=", pid);
      taskkillByPid(pid);
    }

    try { if (fs.existsSync(BACKEND_PID_FILE)) fs.unlinkSync(BACKEND_PID_FILE); } catch {}
    backendProc = null;
  } catch {}
}


function taskkillByPid(pid) {
  if (!pid || !Number.isFinite(pid)) return;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
        windowsHide: true,
        detached: true,
        stdio: "ignore",
      }).unref();
    } else {
      process.kill(pid);
    }
  } catch {}
}

function taskkillByImageName() {
  if (process.platform !== "win32") return;
  try {
    spawn("taskkill", ["/IM", "GestureOSAgent.exe", "/T", "/F"], {
      windowsHide: true,
      detached: true,
      stdio: "ignore",
    }).unref();
  } catch {}
}

function cleanupOldAgent() {
  try {
    if (fs.existsSync(PID_FILE)) {
      const oldPid = parseInt(fs.readFileSync(PID_FILE, "utf-8"), 10);
      if (oldPid) {
        logLine("[agent] cleanup old pid", oldPid);
        taskkillByPid(oldPid);
      }
      try { fs.unlinkSync(PID_FILE); } catch {}
    }
  } catch {}
}

function startAgentNow() {
  try {
    cleanupOldAgent();

    const root = getExtraResourcesRoot();
    const agentExe = path.join(root, "agent", "GestureOSAgent", "GestureOSAgent.exe");

    logLine("[agent] try start. exePath=", agentExe);

    if (!fs.existsSync(agentExe)) {
      logLine("[agent] NOT FOUND:", agentExe);
      return;
    }

    const out = fs.openSync(AGENT_LOG, "a");

    agentProc = spawn(agentExe, [], {
      cwd: path.dirname(agentExe),
      detached: true,
      windowsHide: true,
      stdio: ["ignore", out, out],
    });

    logLine("[agent] started pid=", agentProc.pid);

    try {
      fs.writeFileSync(PID_FILE, String(agentProc.pid), "utf-8");
    } catch {}

    agentProc.on("exit", (code, signal) => {
      logLine("[agent] exit code=", code, "signal=", signal);
    });

    agentProc.on("error", (err) => {
      logLine("[agent] spawn error:", err?.message || err);
    });

    agentProc.unref();
  } catch (e) {
    logLine("[agent] start exception:", e?.message || e);
  }
}

function startAgentAfterRendererReady() {
  if (agentStartScheduled) return;
  agentStartScheduled = true;

  win.webContents.once("did-finish-load", () => {
    logLine("[agent] renderer did-finish-load → start agent");
    setTimeout(() => startAgentNow(), 250);
  });

  setTimeout(() => {
    if (!agentProc) {
      logLine("[agent] fallback timer → start agent");
      startAgentNow();
    }
  }, 6000);
}

function stopAgent() {
  try {
    // PID 기반 종료(가능하면 1번만 호출해서 CMD 플래시 최소화)
    let pid = null;
    try {
      if (fs.existsSync(PID_FILE)) {
        pid = parseInt(fs.readFileSync(PID_FILE, "utf-8"), 10);
      }
    } catch {}

    if (pid) {
      logLine("[agent] stop pid=", pid);
      taskkillByPid(pid);
    } else {
      // PID가 없으면 이름으로 종료
      logLine("[agent] stop fallback taskkill /IM");
      taskkillByImageName();
    }

    // PID 파일 삭제
    try { if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE); } catch {}

    agentProc = null;
  } catch {}
}

// dev 강제 종료(concurrently) 대비
function installProcessGuards() {
  const once = (() => {
    let done = false;
    return (fn) => {
      if (done) return;
      done = true;
      fn();
    };
  })();

  const safeCleanup = () =>
    once(() => {
      logLine("=== process guard cleanup ===");
      stopBackend();
      stopAgent();
    });

  process.on("SIGINT", () => {
    safeCleanup();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    safeCleanup();
    process.exit(0);
  });
  process.on("exit", () => {
    safeCleanup();
  });
  process.on("uncaughtException", () => {
    safeCleanup();
  });
}

// ===============================
// Deep link
// ===============================
function findDeepLinkArg(argv) {
  const prefix = `${PROTOCOL}://`;
  return argv.find((a) => typeof a === "string" && a.startsWith(prefix)) || null;
}

function sendDeepLinkToRenderer(deepLinkUrl) {
  if (!deepLinkUrl) return;
  if (!win) return;
  win.webContents.send("auth:deepLink", deepLinkUrl);
}

function registerProtocolClient() {
  try {
    if (process.defaultApp) {
      const appPath = path.resolve(process.argv[1]);
      app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [appPath]);
    } else {
      app.setAsDefaultProtocolClient(PROTOCOL);
    }
  } catch (e) {
    console.warn("setAsDefaultProtocolClient failed:", e);
  }
}

// Single instance lock
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    const deep = findDeepLinkArg(argv);
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
    if (deep) sendDeepLinkToRenderer(deep);
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    show: false,
    frame: false,
    backgroundColor: "#0b1020",
    autoHideMenuBar: true,
    title: "Gesture Agent Manager",
    icon: ICON_PNG_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: __dirname + "/preload.cjs",
    },
  });

  win.setMenuBarVisibility(false);

  if (app.isPackaged) {
    const indexHtml = path.join(app.getAppPath(), "dist", "index.html");
    win.loadFile(indexHtml);
  } else {
    win.loadURL(DEV_URL);
  }

  // ✅ 창 닫힐 때 app.quit()로 통일해서 before-quit을 "항상" 타게 만든다
  win.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      quitting = true;
      logLine("=== window close → app.quit ===");
      stopBackend();
      stopAgent();          // 먼저 정리 시도
      setTimeout(() => app.quit(), 200);
    }
  });

  win.once("ready-to-show", () => {
    win.maximize();
    win.show();
    startBackendAfterRendererReady();
    startAgentAfterRendererReady();
  });
}

// Window controls (renderer에서 close 누르는 것도 동일하게 quit로)
ipcMain.on("win:minimize", () => win?.minimize());
ipcMain.on("win:toggleMaximize", () => {
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.on("win:close", () => {
  if (!win) return;
  win.close(); // close 이벤트가 app.quit로 연결됨
});

// External open
ipcMain.handle("shell:openExternal", async (_e, url) => {
  if (!url) return false;
  await shell.openExternal(url);
  return true;
});

app.whenReady().then(() => {
  installProcessGuards();

  if (process.platform === "win32") {
    try {
      app.setAppUserModelId("com.gestureos.manager");
    } catch {}
  }

  logLine("=== app start ===", "isPackaged=", app.isPackaged);

  registerProtocolClient();
  createWindow();

  const deep = findDeepLinkArg(process.argv);
  if (deep) setTimeout(() => sendDeepLinkToRenderer(deep), 800);
});

app.on("open-url", (event, url) => {
  event.preventDefault();
  sendDeepLinkToRenderer(url);
});

// 보험: before-quit / window-all-closed 둘 다에서 정리
app.on("before-quit", () => {
  quitting = true;
  logLine("=== before-quit ===");
  stopBackend();
  stopAgent();
});

app.on("window-all-closed", () => {
  logLine("=== window-all-closed ===");
  stopBackend();
  stopAgent();
  if (process.platform !== "darwin") app.quit();
});
