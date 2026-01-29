// front/electron/main.cjs
// - Starts Spring(8080) + Web Spring(8082) + Python Agent(8080 client) after window is visible
// - Quits completely on window close (no background lingering)
// - Robustly kills spawned processes on Windows (PID + commandline fallback)

const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

const ICON_PATH = path.join(__dirname, "assets", "icon.ico");

let win = null;

let isQuitting = false;

const DEV_URL = "http://localhost:5173";
const PROTOCOL = "gestureos";

function isDev() {
  return !app.isPackaged;
}

// -----------------------------
// Common spawn
// -----------------------------
function _spawnHidden(cmd, args, cwd) {
  return spawn(cmd, args, {
    cwd,
    windowsHide: true,
    detached: false,
    stdio: "ignore",
  });
}

// -----------------------------
// Agent (Python exe) - usually talks to manager backend
// -----------------------------
let agentProc = null;
let agentStarting = false;

function getAgentCommand() {
  if (isDev()) {
    const repoRoot = path.join(__dirname, "..", "..");
    const pyMain = path.join(repoRoot, "py", "main.py");
    const pyExe = process.env.GESTUREOS_PYTHON || "python";
    return { cmd: pyExe, args: [pyMain], cwd: path.dirname(pyMain), marker: pyMain };
  }
  const exe = path.join(process.resourcesPath, "agent", "GestureOSAgent.exe");
  return { cmd: exe, args: [], cwd: path.dirname(exe), marker: exe };
}

function startAgentSafe() {
  if (agentProc || agentStarting) return;
  agentStarting = true;

  const { cmd, args, cwd } = getAgentCommand();
  try {
    agentProc = _spawnHidden(cmd, args, cwd);

    agentProc.on("exit", (code) => {
      console.log("[AGENT] exited:", code);
      agentProc = null;
      agentStarting = false;
    });

    agentProc.on("error", (e) => {
      console.error("[AGENT] error:", e);
      agentProc = null;
      agentStarting = false;
    });

    agentStarting = false;
    console.log("[AGENT] started:", cmd, args.join(" "));
  } catch (e) {
    console.error("[AGENT] start failed:", e);
    agentProc = null;
    agentStarting = false;
  }
}

function _killAgentWindowsFallback(markerPath) {
  try {
    const m = String(markerPath || "").replace(/\\/g, "\\\\").replace(/'/g, "''");
    const ps = [
      "$ErrorActionPreference='SilentlyContinue';",
      "Get-Process -Name GestureOSAgent -ErrorAction SilentlyContinue | Stop-Process -Force;",
      `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*${m}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; };`,
      `Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*${m}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; };`,
    ].join(" ");
    _spawnHidden("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], process.cwd());
  } catch {}
}

function stopAgent() {
  const { marker } = getAgentCommand();

  if (agentProc?.pid) {
    try {
      if (process.platform === "win32") {
        _spawnHidden("taskkill", ["/PID", String(agentProc.pid), "/T", "/F"], process.cwd());
      } else {
        agentProc.kill("SIGTERM");
      }
    } catch {}
  }

  if (process.platform === "win32") _killAgentWindowsFallback(marker);

  agentProc = null;
  agentStarting = false;
}

// -----------------------------
// Spring backends (2개): manager(8080) + web(auth)(8082)
// -----------------------------
let managerProc = null;
let managerStarting = false;

let webProc = null;
let webStarting = false;

function getManagerSpringCommand() {
  if (isDev()) return null;
  const jar = path.join(process.resourcesPath, "backend", "gestureosmanager.jar");
  const javaExe = process.env.GESTUREOS_JAVA || "java";
  // ✅ 8080 고정(혹시 설정파일로 바뀌어도 강제)
  return { cmd: javaExe, args: ["-jar", jar, "--server.port=8080"], cwd: path.dirname(jar), marker: jar };
}

function getWebSpringCommand() {
  if (isDev()) return null;
  const jar = path.join(process.resourcesPath, "webbackend", "webbackend.jar");
  const javaExe = process.env.GESTUREOS_JAVA || "java";
  // ✅ 8082 고정
  return { cmd: javaExe, args: ["-jar", jar, "--server.port=8082"], cwd: path.dirname(jar), marker: jar };
}

function startSpringSafe(kind) {
  if (kind === "MANAGER") {
    if (managerProc || managerStarting) return;
    const spec = getManagerSpringCommand();
    if (!spec) return;

    managerStarting = true;
    const { cmd, args, cwd } = spec;

    try {
      managerProc = _spawnHidden(cmd, args, cwd);
      managerProc.on("exit", (code) => {
        console.log("[SPRING:8080] exited:", code);
        managerProc = null;
        managerStarting = false;
      });
      managerProc.on("error", (e) => {
        console.error("[SPRING:8080] error:", e);
        managerProc = null;
        managerStarting = false;
      });

      managerStarting = false;
      console.log("[SPRING:8080] started:", cmd, args.join(" "));
    } catch (e) {
      console.error("[SPRING:8080] start failed:", e);
      managerProc = null;
      managerStarting = false;
    }
    return;
  }

  if (kind === "WEB") {
    if (webProc || webStarting) return;
    const spec = getWebSpringCommand();
    if (!spec) return;

    webStarting = true;
    const { cmd, args, cwd } = spec;

    try {
      webProc = _spawnHidden(cmd, args, cwd);
      webProc.on("exit", (code) => {
        console.log("[SPRING:8082] exited:", code);
        webProc = null;
        webStarting = false;
      });
      webProc.on("error", (e) => {
        console.error("[SPRING:8082] error:", e);
        webProc = null;
        webStarting = false;
      });

      webStarting = false;
      console.log("[SPRING:8082] started:", cmd, args.join(" "));
    } catch (e) {
      console.error("[SPRING:8082] start failed:", e);
      webProc = null;
      webStarting = false;
    }
  }
}

function _killJavaByMarkerWindows(markerPath) {
  try {
    const m = String(markerPath || "").replace(/\\/g, "\\\\").replace(/'/g, "''");
    const ps = [
      "$ErrorActionPreference='SilentlyContinue';",
      `Get-CimInstance Win32_Process -Filter "Name='java.exe'" | Where-Object { $_.CommandLine -like '*${m}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; };`,
    ].join(" ");
    _spawnHidden("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], process.cwd());
  } catch {}
}

function stopSpring(kind) {
  if (kind === "MANAGER") {
    const spec = getManagerSpringCommand();
    const marker = spec?.marker || "gestureosmanager.jar";

    if (managerProc?.pid) {
      try {
        if (process.platform === "win32") {
          _spawnHidden("taskkill", ["/PID", String(managerProc.pid), "/T", "/F"], process.cwd());
        } else {
          managerProc.kill("SIGTERM");
        }
      } catch {}
    }
    if (process.platform === "win32") _killJavaByMarkerWindows(marker);

    managerProc = null;
    managerStarting = false;
    return;
  }

  if (kind === "WEB") {
    const spec = getWebSpringCommand();
    const marker = spec?.marker || "webbackend.jar";

    if (webProc?.pid) {
      try {
        if (process.platform === "win32") {
          _spawnHidden("taskkill", ["/PID", String(webProc.pid), "/T", "/F"], process.cwd());
        } else {
          webProc.kill("SIGTERM");
        }
      } catch {}
    }
    if (process.platform === "win32") _killJavaByMarkerWindows(marker);

    webProc = null;
    webStarting = false;
  }
}

function stopAllBackends() {
  stopAgent();
  stopSpring("MANAGER");
  stopSpring("WEB");
}

// -----------------------------
// Deep link / single instance
// -----------------------------
function findDeepLinkArg(argv) {
  const prefix = `${PROTOCOL}://`;
  return argv.find((a) => typeof a === "string" && a.startsWith(prefix)) || null;
}

function sendDeepLinkToRenderer(deepLinkUrl) {
  if (!deepLinkUrl || !win) return;
  try { win.webContents.send("auth:deepLink", deepLinkUrl); } catch {}
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

function ensureWindow() {
  if (!win || win.isDestroyed()) {
    createWindow();
    return;
  }
  try {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  } catch {}
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    const deep = findDeepLinkArg(argv);
    ensureWindow();
    if (deep) sendDeepLinkToRenderer(deep);
  });
}

// -----------------------------
// Window 생성
// -----------------------------
function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    show: false,
    frame: false,
    backgroundColor: "#0b1020",
    autoHideMenuBar: true,
    title: "Gesture Agent Manager",
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  win.setMenuBarVisibility(false);

  win.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      isQuitting = true;

      stopAllBackends();

      setTimeout(() => {
        try { app.exit(0); } catch {}
      }, 1200);

      app.quit();
      return;
    }
    stopAllBackends();
  });

  win.on("closed", () => {
    win = null;
  });

  if (isDev()) {
    win.loadURL(DEV_URL);
  } else {
    const indexHtml = path.join(__dirname, "..", "dist", "index.html");
    win.loadFile(indexHtml);
  }

  // 창 보여주고 -> 8080 -> 8082 -> Agent 순
  let shown = false;

  win.once("ready-to-show", () => {
    shown = true;
    try { win.maximize(); } catch {}
    try { win.show(); win.focus(); } catch {}

    setTimeout(() => startSpringSafe("MANAGER"), 200);
    setTimeout(() => startSpringSafe("WEB"), 700);
    setTimeout(startAgentSafe, 1200);
  });

  setTimeout(() => {
    if (!win || win.isDestroyed()) return;
    if (shown) return;
    try { win.show(); win.focus(); } catch {}

    setTimeout(() => startSpringSafe("MANAGER"), 200);
    setTimeout(() => startSpringSafe("WEB"), 700);
    setTimeout(startAgentSafe, 1200);
  }, 2000);
}

// -----------------------------
// IPC Window controls
// -----------------------------
ipcMain.on("win:minimize", () => {
  try { win?.minimize(); } catch {}
});

ipcMain.on("win:toggleMaximize", () => {
  if (!win) return;
  try { win.isMaximized() ? win.unmaximize() : win.maximize(); } catch {}
});

ipcMain.on("win:close", () => {
  isQuitting = true;
  stopAllBackends();
  setTimeout(() => {
    try { app.exit(0); } catch {}
  }, 1200);
  app.quit();
});

ipcMain.handle("shell:openExternal", async (_e, url) => {
  if (!url) return false;
  await shell.openExternal(url);
  return true;
});

// -----------------------------
// App lifecycle
// -----------------------------
app.whenReady().then(() => {
  if (process.platform === "win32") {
    try { app.setAppUserModelId("com.gestureos.manager"); } catch {}
  }

  registerProtocolClient();
  createWindow();

  const deep = findDeepLinkArg(process.argv);
  if (deep) setTimeout(() => sendDeepLinkToRenderer(deep), 800);
});

app.on("before-quit", () => {
  isQuitting = true;
  stopAllBackends();
});

app.on("window-all-closed", () => {
  stopAllBackends();
  if (process.platform !== "darwin") app.quit();
});
