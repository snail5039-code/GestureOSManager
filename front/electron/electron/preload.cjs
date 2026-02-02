const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("managerWin", {
  minimize: () => ipcRenderer.send("win:minimize"),
  toggleMaximize: () => ipcRenderer.send("win:toggleMaximize"),
  close: () => ipcRenderer.send("win:close"),

  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),

  onDeepLink: (cb) => {
    const handler = (_e, url) => cb?.(url);
    ipcRenderer.on("auth:deepLink", handler);
    return () => ipcRenderer.removeListener("auth:deepLink", handler);
  },
});
