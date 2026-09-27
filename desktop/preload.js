"use strict";

const { contextBridge, ipcRenderer } = require("electron");

// Keep the renderer surface intentionally small. No Node primitive, path, or
// unrestricted IPC channel is exposed to the web application.
contextBridge.exposeInMainWorld("mirofishDesktop", Object.freeze({
  isDesktop: true,
  platform: process.platform,
  showWindow: () => ipcRenderer.invoke("window:show"),
  hideWindow: () => ipcRenderer.invoke("window:hide"),
  restartEngine: () => ipcRenderer.invoke("engine:restart"),
  getServerState: () => ipcRenderer.invoke("server:state"),
  onServerState: (callback) => {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, state) => callback(state);
    ipcRenderer.on("server:state", listener);
    return () => ipcRenderer.removeListener("server:state", listener);
  },
}));
