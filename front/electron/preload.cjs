// 1. Electron에서 보안 통로(contextBridge)와 통신 모듈(ipcRenderer)을 불러옵니다.
const { contextBridge, ipcRenderer } = require("electron");

// 2. contextBridge를 사용해 메인 프로세스의 기능을 웹 페이지(Main World)에 공개합니다.
// 웹 페이지의 window 객체에 "managerWin"이라는 이름의 보관함을 하나 만든다고 생각하면 됩니다.
contextBridge.exposeInMainWorld("managerWin", {
  
  // 3. 창 최소화 기능: 웹에서 호출하면 메인 프로세스로 "win:minimize"라는 신호를 보냅니다.
  minimize: () => ipcRenderer.send("win:minimize"),

  // 4. 창 최대화/복구 기능: 웹에서 호출하면 메인 프로세스로 "win:toggleMaximize" 신호를 보냅니다.
  toggleMaximize: () => ipcRenderer.send("win:toggleMaximize"),

  // 5. 창 닫기 기능: 웹에서 호출하면 메인 프로세스로 "win:close" 신호를 보냅니다.
  close: () => ipcRenderer.send("win:close"),
});