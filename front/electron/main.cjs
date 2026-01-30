const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const net = require("net");
const { spawn, spawnSync } = require("child_process");

const ICON_PATH = path.join(__dirname, "assets", "icon.png");

let win;
const DEV_URL = "http://localhost:5173";
const PROTOCOL = "gestureos";

let managerProc = null;
let agentProc = null;

// ------------------------------
// Manager PID tracking (Windows)
// ------------------------------
function managerPidFile() {
  // startManagerJar is only called after app is ready.
  return path.join(app.getPath("userData"), "GestureOSManager.pid");
}

function readManagerPid() {
  try {
    const p = parseInt(String(fs.readFileSync(managerPidFile(), "utf8")).trim(), 10);
    return Number.isFinite(p) ? p : null;
  } catch {
    return null;
  }
}

function writeManagerPid(pid) {
  try {
    fs.writeFileSync(managerPidFile(), String(pid), "utf8");
  } catch {}
}

function clearManagerPid() {
  try {
    fs.unlinkSync(managerPidFile());
  } catch {}
}

// ------------------------------
// Windows process tree kill (no visible console)
// ------------------------------
function killTreeWinSync(pid) {
  if (!pid) return false;

  // Prefer PowerShell hidden window.
  // taskkill is used internally to ensure child-process tree is terminated (/T).
  const ps = "try { taskkill /PID " + String(pid) + " /T /F | Out-Null } catch { }";
  try {
    const r = spawnSync(
      "powershell.exe",
      ["-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
      { windowsHide: true, stdio: "ignore" }
    );
    if (!r.error) return true;
  } catch {}

  // Fallback: direct taskkill (still hidden).
  try {
    spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    return true;
  } catch {
    return false;
  }
}

// ------------------------------
// Agent PID tracking (no tasklist/taskkill)
// ------------------------------
function agentPidFile() {
  // startAgentExe is only called after app is ready.
  return path.join(app.getPath("userData"), "GestureOSAgent.pid");
}

function readAgentPid() {
  try {
    const p = parseInt(String(fs.readFileSync(agentPidFile(), "utf8")).trim(), 10);
    return Number.isFinite(p) ? p : null;
  } catch {
    return null;
  }
}

function writeAgentPid(pid) {
  try {
    fs.writeFileSync(agentPidFile(), String(pid), "utf8");
  } catch {}
}

function clearAgentPid() {
  try {
    fs.unlinkSync(agentPidFile());
  } catch {}
}

// ------------------------------
// Deep link
// ------------------------------
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

// ------------------------------
// ✅ Single instance (중복 실행 방지 핵심)
// ------------------------------
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  // lock 실패면 절대 whenReady로 진행하면 안 됨
  app.quit();
  // Windows에서 더 확실히 끊고 싶으면:
  process.exit(0);
}

app.on("second-instance", (_event, argv) => {
  const deep = findDeepLinkArg(argv);
  if (win) {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }
  if (deep) sendDeepLinkToRenderer(deep);
});

// ------------------------------
// Renderer URL (dev/prod)
// ------------------------------
function resolveProdIndexHtml() {
  const candidates = [
    path.join(__dirname, "..", "dist", "index.html"),
    path.join(__dirname, "dist", "index.html"),
    path.join(__dirname, "renderer", "index.html"),
    path.join(process.resourcesPath, "front", "dist", "index.html"),
    path.join(process.resourcesPath, "front", "index.html"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
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
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  win.setMenuBarVisibility(false);

  if (app.isPackaged) {
    const prodIndex = resolveProdIndexHtml();
    if (prodIndex) win.loadFile(prodIndex);
    else win.loadURL(DEV_URL);
  } else {
    win.loadURL(DEV_URL);
  }

  win.once("ready-to-show", () => {
    win.maximize();
    win.show();
  });
}

// ------------------------------
// Child processes
// ------------------------------
function resourcesBase() {
  // dev: front/electron 기준 -> 프로젝트 루트(GestureOSManager)로 나가야 jar/py 경로가 맞음
  return app.isPackaged ? process.resourcesPath : path.join(__dirname, "..", "..");
}

function isPortOpen(host, port, timeoutMs = 500) {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    const done = (ok) => {
      try { sock.destroy(); } catch {}
      resolve(ok);
    };
    sock.setTimeout(timeoutMs);
    sock.once("connect", () => done(true));
    sock.once("timeout", () => done(false));
    sock.once("error", () => done(false));
    sock.connect(port, host);
  });
}

async function waitForPort(host, port, totalWaitMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < totalWaitMs) {
    if (await isPortOpen(host, port, 300)) return true;
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

function isPidAlive(pid) {
  if (!pid) return false;
  try {
    // On Windows this does not spawn cmd.exe; it uses native process APIs.
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function startManagerJar() {
  const base = resourcesBase();

  const jarPath = app.isPackaged
    ? path.join(base, "bin", "gestureOSManager.jar")
    : path.join(base, "gestureOSManager", "target", "gestureOSManager-0.0.1-SNAPSHOT.jar");

  if (!fs.existsSync(jarPath)) {
    console.warn("[BOOT] manager jar not found:", jarPath);
    return;
  }

  // Avoid double-spawn without calling tasklist (prevents cmd/conhost flashes)
  if (process.platform === "win32") {
    const prevPid = readManagerPid();
    if (prevPid && isPidAlive(prevPid)) {
      console.warn("[BOOT] manager already running (pidfile) -> skip spawn");
      return;
    }
    if (prevPid && !isPidAlive(prevPid)) {
      clearManagerPid();
    }
  }

  const javaExe = process.platform === "win32" ? "javaw" : "java";
  managerProc = spawn(javaExe, ["-jar", jarPath], {
    windowsHide: true,
    env: process.env,
    stdio: "ignore",
  });

  if (process.platform === "win32") {
    writeManagerPid(managerProc.pid);
  }

  managerProc.on("exit", () => {
    managerProc = null;
    if (process.platform === "win32") clearManagerPid();
  });
}

function startAgentExe() {
  const base = resourcesBase();

  const exePath = app.isPackaged
    ? path.join(base, "bin", "GestureOSAgent", "GestureOSAgent.exe")
    : path.join(base, "py", "dist", "GestureOSAgent", "GestureOSAgent.exe");

  if (!fs.existsSync(exePath)) {
    console.warn("[BOOT] agent exe not found:", exePath);
    return;
  }

  // Avoid double-spawn without calling tasklist (prevents cmd/conhost flashes)
  if (process.platform === "win32") {
    const prevPid = readAgentPid();
    if (prevPid && isPidAlive(prevPid)) {
      console.warn("[BOOT] agent already running (pidfile) -> skip spawn");
      return;
    }
    if (prevPid && !isPidAlive(prevPid)) {
      clearAgentPid();
    }
  }

  agentProc = spawn(exePath, [], {
    windowsHide: true,
    env: process.env,
    stdio: "ignore",
  });

  if (process.platform === "win32") {
    writeAgentPid(agentProc.pid);
  }

  agentProc.on("exit", () => {
    agentProc = null;
    if (process.platform === "win32") clearAgentPid();
  });
}

function stopChildren() {
  if (process.platform !== "win32") {
    try { agentProc?.kill("SIGTERM"); } catch {}
    try { managerProc?.kill("SIGTERM"); } catch {}
    agentProc = null;
    managerProc = null;
    return;
  }

  // ✅ Kill full process tree to ensure HUD overlay (child mp.Process) is terminated.
  const agentPid = agentProc?.pid || readAgentPid();
  const mgrPid = managerProc?.pid || readManagerPid();

  killTreeWinSync(agentPid);
  killTreeWinSync(mgrPid);

  clearAgentPid();
  clearManagerPid();

  agentProc = null;
  managerProc = null;
}

// ------------------------------
// IPC
// ------------------------------
ipcMain.on("win:minimize", () => win?.minimize());
ipcMain.on("win:toggleMaximize", () => {
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.on("win:close", () => win?.close());

ipcMain.handle("shell:openExternal", async (_e, url) => {
  if (!url) return false;
  await shell.openExternal(url);
  return true;
});

// ------------------------------
// App lifecycle
// ------------------------------
app.whenReady().then(async () => {
  if (process.platform === "win32") {
    try { app.setAppUserModelId("com.gestureos.manager"); } catch {}
  }

  registerProtocolClient();
  createWindow();

  // manager(8080) → agent 순서
  const alreadyUp = await isPortOpen("127.0.0.1", 8080, 300);
  if (!alreadyUp) {
    startManagerJar();
    await waitForPort("127.0.0.1", 8080, 15000);
  }
  startAgentExe();

  const deep = findDeepLinkArg(process.argv);
  if (deep) setTimeout(() => sendDeepLinkToRenderer(deep), 800);
});

app.on("open-url", (event, url) => {
  event.preventDefault();
  sendDeepLinkToRenderer(url);
});

app.on("before-quit", () => stopChildren());

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    stopChildren();
    app.quit();
  }
});
