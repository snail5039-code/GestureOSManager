// electron/preload.cjs
// Patched: expose window.managerWin (and window.electron for backward compatibility)
const { contextBridge, ipcRenderer } = require("electron");

const api = {
  minimize: () => ipcRenderer.send("win:minimize"),
  toggleMaximize: () => ipcRenderer.send("win:toggleMaximize"),
  close: () => ipcRenderer.send("win:close"),

  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),

  onDeepLink: (cb) => {
    const handler = (_e, url) => cb(url);
    ipcRenderer.on("auth:deepLink", handler);
    return () => ipcRenderer.removeListener("auth:deepLink", handler);
  },
};

// ✅ React 코드가 기대하는 이름
contextBridge.exposeInMainWorld("managerWin", api);

// (옵션) 기존/다른 코드 호환용
contextBridge.exposeInMainWorld("electron", api);
