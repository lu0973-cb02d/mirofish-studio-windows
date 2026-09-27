const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('mirofishDesktop', Object.freeze({
  version: '1.1.0',
  getStatus: () => ipcRenderer.invoke('desktop:get-status'),
  chooseRoot: () => ipcRenderer.invoke('desktop:choose-root'),
  setRoot: (root) => ipcRenderer.invoke('desktop:set-root', root),
  restartEngine: () => ipcRenderer.invoke('desktop:restart-engine'),
  openDataFolder: () => ipcRenderer.invoke('desktop:open-data-folder'),
  openGuide: () => ipcRenderer.invoke('desktop:open-guide'),
  showWindow: () => ipcRenderer.invoke('desktop:show-window'),
  quit: () => ipcRenderer.invoke('desktop:quit')
}))
