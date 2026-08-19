const { app, BrowserWindow, ipcMain, shell, protocol, net } = require("electron");
const path = require("path");
const { pathToFileURL } = require("node:url");

// App icon (BrowserWindow icon is not always used on Windows taskbar in dev;
// packaged EXE icon should be configured separately for production builds.)
const ICON_PATH = path.join(__dirname, "assets", "icon.png");

let win;
const DEV_URL = "http://localhost:5173";
const PROTOCOL = "gestureos";

// ============================================================================
// 패키징 실행 경로
//
// 개발 중에는 Vite dev server(5173)를 열고, /api 요청은 vite.config.js 의 proxy 가
// 8080(에이전트)과 8082(계정)로 갈라준다. 패키징하면 dev server 도 proxy 도 없으므로
// 예전에는 화면 자체가 뜨지 않았고, 떠도 모든 /api 요청이 갈 곳을 잃었다.
//
// 그래서 앱 전용 스킴(gosapp://)을 등록하고, 메인 프로세스가
//   - 정적 파일: dist/ 에서 읽어 주고
//   - /api, /motion: dev proxy 와 같은 규칙으로 백엔드에 중계한다
// 렌더러는 계속 "/api/..." 상대 경로를 쓰면 되고(동일 오리진), 백엔드 CORS 설정도
// 그대로 둘 수 있다.
// ============================================================================
const APP_SCHEME = "gosapp";
const APP_ORIGIN = `${APP_SCHEME}://app`;
const DIST_DIR = path.join(__dirname, "..", "dist");

const BACKEND_ORIGINS = {
  agent: process.env.GOS_AGENT_ORIGIN || "http://127.0.0.1:8080",
  account: process.env.GOS_ACCOUNT_ORIGIN || "http://127.0.0.1:8082",
};

// 라우팅 규칙은 테스트할 수 있게 electron 의존 없는 모듈로 분리해 두었다.
const { resolveApiTarget, resolveDistPath } = require("./apiRoutes.cjs");

// 앱 전용 스킴은 app ready 전에 등록해야 한다.
protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
  },
]);

/** 중계 요청에서 빼야 하는 헤더. Origin 을 그대로 넘기면 서버가 CORS 로 막는다. */
const STRIPPED_HEADERS = new Set(["origin", "referer", "host", "connection"]);

function forwardHeaders(headers) {
  const out = {};
  for (const [k, v] of headers) {
    if (!STRIPPED_HEADERS.has(k.toLowerCase())) out[k] = v;
  }
  return out;
}

async function proxyToBackend(request, target) {
  const url = new URL(request.url);
  const upstream = target + url.pathname + url.search;

  const init = {
    method: request.method,
    headers: forwardHeaders(request.headers),
    // 계정 API 는 refreshToken 쿠키를 쓴다. 쿠키는 세션 저장소가 관리한다.
    credentials: "include",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }

  try {
    return await net.fetch(upstream, init);
  } catch (e) {
    console.warn("[PROXY] 백엔드에 연결할 수 없음:", upstream, e?.message);
    return new Response(
      JSON.stringify({ ok: false, error: "BACKEND_UNREACHABLE", target: upstream }),
      { status: 502, headers: { "content-type": "application/json; charset=utf-8" } },
    );
  }
}

async function serveFromDist(pathname) {
  const filePath = resolveDistPath(pathname, DIST_DIR);

  // dist 밖을 읽으려는 요청은 거부한다.
  if (!filePath) return new Response("Forbidden", { status: 403 });

  try {
    return await net.fetch(pathToFileURL(filePath).toString());
  } catch {
    return new Response("Not Found", { status: 404 });
  }
}

function registerAppProtocol() {
  protocol.handle(APP_SCHEME, async (request) => {
    const url = new URL(request.url);
    const target = resolveApiTarget(url.pathname, BACKEND_ORIGINS);
    return target ? proxyToBackend(request, target) : serveFromDist(url.pathname);
  });
}

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

  if (app.isPackaged) {
    win.loadURL(`${APP_ORIGIN}/index.html`);
  } else {
    win.loadURL(DEV_URL);
  }

  win.once("ready-to-show", () => {
    win.maximize();
    win.show();
  });

  // 창이 닫힌 뒤에도 win 이 남아 있으면 창 조작 IPC 가 파괴된 객체를 건드린다.
  win.on("closed", () => {
    win = null;
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
  registerAppProtocol();
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
