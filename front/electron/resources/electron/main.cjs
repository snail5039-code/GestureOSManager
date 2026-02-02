const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

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

function taskkillByPid(pid) {
  if (!pid || !Number.isFinite(pid)) return;
  try {
    if (process.platform === "win32") {
      spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
        windowsHide: true,
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
    // 1) PID 기반 종료
    let pid = null;
    try {
      if (fs.existsSync(PID_FILE)) {
        pid = parseInt(fs.readFileSync(PID_FILE, "utf-8"), 10);
      }
    } catch {}

    if (pid) {
      logLine("[agent] stop pid=", pid);
      taskkillByPid(pid);
    }

    // 2) PID 파일 삭제
    try { if (fs.existsSync(PID_FILE)) fs.unlinkSync(PID_FILE); } catch {}

    // 3) 0.5초 뒤 이름으로 한 번 더 정리(트리/자식 남는 케이스 대응)
    setTimeout(() => {
      logLine("[agent] stop fallback taskkill /IM");
      taskkillByImageName();
    }, 500);

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
      stopAgent();          // 먼저 정리 시도
      setTimeout(() => app.quit(), 200);
    }
  });

  win.once("ready-to-show", () => {
    win.maximize();
    win.show();
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
  stopAgent();
});

app.on("window-all-closed", () => {
  logLine("=== window-all-closed ===");
  stopAgent();
  if (process.platform !== "darwin") app.quit();
});
