// 1. Electron에서 필요한 모듈(앱 관리, 창 생성, 프로세스 간 통신)을 가져옵니다.
const { app, BrowserWindow, ipcMain } = require("electron");

// 2. 창 객체를 담을 변수를 선언하고, 접속할 Vite 개발 서버 주소를 상수로 정의합니다.
let win;
const DEV_URL = "http://localhost:5173";

// 3. 메인 창을 생성하고 설정하는 함수입니다.
function createWindow() {
  win = new BrowserWindow({
    width: 1200,            // 창의 초기 가로 너비
    height: 800,           // 창의 초기 세로 높이
    show: false,           // ⚠️ 중요: 창이 로딩되기 전엔 숨겨서 '하얀 화면' 깜빡임을 방지합니다.
    frame: false,          // 기본 상단바와 테두리를 제거 (커스텀 디자인용)
    backgroundColor: "#0b1020", // 창이 뜨기 전이나 로딩 중에 보여줄 배경색 (다크 모드)
    autoHideMenuBar: true, // 메뉴바 자동 숨김
    title: "Gesture Agent Manager", // 앱의 이름 (작업 표시줄 등 표시)

    webPreferences: {
      contextIsolation: true, // 렌더러와 메인 환경 격리 (보안)
      nodeIntegration: false, // 브라우저 내 Node.js 직접 사용 금지 (보안)
      preload: __dirname + "/preload.cjs", // 다리 역할을 할 프리로드 스크립트 연결
    },
  });

  // 상단 메뉴바를 완전히 보이지 않게 설정합니다.
  win.setMenuBarVisibility(false);

  // 지정된 URL(Vite 서버)을 창에 로드합니다.
  win.loadURL(DEV_URL);

  // 창이 화면에 그려질 준비가 한 번 완료되었을 때 실행됩니다.
  win.once("ready-to-show", () => {
    win.minimize(); // 창을 최대화하고
    win.show();     // 숨겨두었던 창을 화면에 나타냅니다. (부드러운 실행)
  });
}

// 4. 창 제어를 위한 통신(IPC) 수신부 설정
// 렌더러(프론트엔드)에서 보내는 최소화, 최대화, 닫기 신호를 처리합니다.
ipcMain.on("win:minimize", () => win?.minimize()); // 최소화

ipcMain.on("win:toggleMaximize", () => {
  if (!win) return;
  // 현재 최대화 상태면 원래대로, 아니면 최대화로 전환합니다.
  win.isMaximized() ? win.unmaximize() : win.maximize();
});

ipcMain.on("win:close", () => win?.close()); // 닫기

// 5. 앱이 준비되면 창 생성 함수를 실행합니다.
app.whenReady().then(createWindow);

// 6. 모든 창이 닫혔을 때 앱 종료 설정 (macOS 제외)
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});