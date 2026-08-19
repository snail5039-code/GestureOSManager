const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("managerWin", {
  minimize: () => ipcRenderer.send("win:minimize"),
  toggleMaximize: () => ipcRenderer.send("win:toggleMaximize"),
  close: () => ipcRenderer.send("win:close"),

  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),

  // 매니저 서버는 WebSocket 접속에도 로컬 세션 토큰을 요구한다.
  // 브라우저 WebSocket API 로는 헤더를 붙일 수 없어서 쿼리로 보내야 하고,
  // 그래서 이 값만은 렌더러가 알아야 한다. (HTTP 는 메인 프로세스가 붙인다)
  getWsToken: () => ipcRenderer.invoke("auth:wsToken"),

  onDeepLink: (cb) => {
    const handler = (_e, url) => cb?.(url);
    ipcRenderer.on("auth:deepLink", handler);
    return () => ipcRenderer.removeListener("auth:deepLink", handler);
  },
});
