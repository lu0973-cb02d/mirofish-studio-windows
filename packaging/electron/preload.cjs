const { contextBridge } = require('electron');
contextBridge.exposeInMainWorld('mirofishDesktop', { packaged: true });
