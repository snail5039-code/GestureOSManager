const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("path");

// App icon (BrowserWindow icon is not always used on Windows taskbar in dev;
// packaged EXE icon should be configured separately for production builds.)
const ICON_PATH = path.join(__dirname, "assets", "icon.png");

let win;
const DEV_URL = "http://localhost:5173";
const PROTOCOL = "gestureos";

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
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: __dirname + "/preload.cjs",
    },
  });

  win.setMenuBarVisibility(false);
  win.loadURL(DEV_URL);

  win.once("ready-to-show", () => {
    win.maximize();
    win.show();
  });
}

// Window controls
ipcMain.on("win:minimize", () => win?.minimize());
ipcMain.on("win:toggleMaximize", () => {
  if (!win) return;
  win.isMaximized() ? win.unmaximize() : win.maximize();
});
ipcMain.on("win:close", () => win?.close());

// External open
ipcMain.handle("shell:openExternal", async (_e, url) => {
  if (!url) return false;
  await shell.openExternal(url);
  return true;
});

app.whenReady().then(() => {
  // Helps Windows group the taskbar icon correctly.
  if (process.platform === "win32") {
    try {
      app.setAppUserModelId("com.gestureos.manager");
    } catch {}
  }
  registerProtocolClient();
  createWindow();

  const deep = findDeepLinkArg(process.argv);
  if (deep) setTimeout(() => sendDeepLinkToRenderer(deep), 800);
});

// macOS
app.on("open-url", (event, url) => {
  event.preventDefault();
  sendDeepLinkToRenderer(url);
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
