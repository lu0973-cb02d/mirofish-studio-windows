"use strict";

const { app, BrowserWindow, Menu, Tray, nativeImage, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const https = require("https");
const os = require("os");
const path = require("path");

const PORT = 3888;
const HOST = "127.0.0.1";
const STUDIO_URL = `http://${HOST}:${PORT}`;
const STUDIO_HEADER = { "X-MiroFish-Studio": "1" };
const APP_ROOT = path.resolve(__dirname, "..");
const DEV_MODE = process.argv.includes("--dev") || !app.isPackaged;

let mainWindow = null;
let tray = null;
let serverProcess = null;
let ownsServer = false;
let isQuitting = false;
let healthTimer = null;

function exists(directory) {
  try {
    return fs.statSync(directory).isDirectory();
  } catch (_error) {
    return false;
  }
}

function isMiroFishRoot(directory) {
  return Boolean(directory) && exists(directory) &&
    fs.existsSync(path.join(directory, "local_studio", "server.py"));
}

function resolveMiroFishRoot() {
  const candidates = [
    process.env.MIROFISH_ROOT,
    app.isPackaged ? path.join(process.resourcesPath, "mirofish") : null,
    APP_ROOT,
    path.join(path.dirname(process.execPath), "MiroFish"),
    path.join(os.homedir(), "MiroFish"),
    path.join(app.getPath("documents"), "MiroFish"),
    path.join(app.getPath("desktop"), "MiroFish"),
  ];
  return candidates.find(isMiroFishRoot) || null;
}

function iconPath(name = "mirofish.ico") {
  return path.join(__dirname, "assets", name);
}

function isLocalStudioUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" && url.hostname === HOST && Number(url.port || 80) === PORT;
  } catch (_error) {
    return false;
  }
}

function requestStudio(pathname, options = {}) {
  const method = options.method || "GET";
  const body = options.body ? JSON.stringify(options.body) : null;
  const headers = { ...STUDIO_HEADER, ...(options.headers || {}) };
  if (body) {
    headers["Content-Type"] = "application/json";
    headers["Content-Length"] = Buffer.byteLength(body);
  }
  return new Promise((resolve, reject) => {
    const request = http.request({
      hostname: HOST,
      port: PORT,
      path: pathname,
      method,
      headers,
      timeout: options.timeout || 2500,
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        let data = null;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (_error) {
          data = null;
        }
        resolve({ status: response.statusCode || 0, data });
      });
    });
    request.on("timeout", () => request.destroy(new Error("studio request timed out")));
    request.on("error", reject);
    if (body) request.write(body);
    request.end();
  });
}

async function studioHealth() {
  try {
    const result = await requestStudio("/studio-health", { headers: {} });
    return result.status === 200 && result.data && result.data.service === "MiroFish Studio"
      ? { online: true, ...result.data }
      : { online: false };
  } catch (_error) {
    return { online: false };
  }
}

function emitServerState(state) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send("server:state", state);
  if (tray) tray.setToolTip(state.online ? "MiroFish Studio · 运行中" : "MiroFish Studio · 正在启动");
}

async function waitForStudio(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await studioHealth();
    if (state.online) return state;
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  return studioHealth();
}

function startStudioServer(root) {
  if (serverProcess && !serverProcess.killed) return;
  const backend = path.join(root, "backend");
  const windowsPython = path.join(backend, ".venv", "Scripts", "pythonw.exe");
  const consolePython = path.join(backend, ".venv", "Scripts", "python.exe");
  const python = fs.existsSync(windowsPython) ? windowsPython :
    (fs.existsSync(consolePython) ? consolePython : null);
  if (!python) {
    throw new Error("没有找到 backend/.venv。请先运行完整安装包，或设置 MIROFISH_ROOT 指向已有安装。");
  }
  const data = path.join(root, "studio_data");
  fs.mkdirSync(data, { recursive: true });
  const logPath = path.join(data, "studio-desktop.log");
  const log = fs.createWriteStream(logPath, { flags: "a" });
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" };
  serverProcess = spawn(python, ["-X", "utf8", "-m", "local_studio.server"], {
    cwd: root,
    env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  ownsServer = true;
  serverProcess.stdout.pipe(log);
  serverProcess.stderr.pipe(log);
  serverProcess.once("exit", () => {
    log.end();
    serverProcess = null;
    emitServerState({ online: false });
  });
}

function buildApplicationMenu() {
  const template = [
    {
      label: "MiroFish",
      submenu: [
        { label: "显示工作台", accelerator: "CmdOrCtrl+Shift+M", click: () => showWindow() },
        { type: "separator" },
        { label: "退出 MiroFish", accelerator: "CmdOrCtrl+Q", click: () => app.quit() },
      ],
    },
    {
      label: "引擎",
      submenu: [
        { label: "重启推演引擎", accelerator: "CmdOrCtrl+Shift+R", click: () => restartEngine() },
      ],
    },
    {
      label: "窗口",
      submenu: [
        { label: "最小化到托盘", click: () => mainWindow?.hide() },
        { label: "重新加载工作台", click: () => mainWindow?.reload() },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

async function restartEngine() {
  try {
    const response = await requestStudio("/studio-api/engine/restart", { method: "POST", timeout: 60000 });
    if (response.status >= 400) throw new Error("engine restart rejected");
    showWindow();
  } catch (error) {
    emitServerState({ online: false, error: "重启推演引擎失败，请在工作台查看详情。" });
  }
}

function createTray() {
  const source = nativeImage.createFromPath(iconPath("mirofish-tray.png"));
  tray = new Tray(source.isEmpty() ? nativeImage.createFromPath(iconPath()) : source);
  tray.setToolTip("MiroFish Studio · 正在启动");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开 MiroFish 工作台", click: () => showWindow() },
    { type: "separator" },
    { label: "重启推演引擎", click: () => restartEngine() },
    { label: "退出", click: () => app.quit() },
  ]));
  tray.on("click", () => showWindow());
}

function protectWindow(window) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isLocalStudioUrl(url)) return { action: "allow" };
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (!isLocalStudioUrl(url)) event.preventDefault();
  });
  window.webContents.on("before-input-event", (event, input) => {
    const key = String(input.key || "").toLowerCase();
    if (key === "f12" || (input.control && input.shift && key === "i") ||
        (input.meta && input.alt && key === "i")) event.preventDefault();
  });
  window.webContents.on("did-finish-load", () => studioHealth().then(emitServerState));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    backgroundColor: "#f6f7f5",
    icon: iconPath(),
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      devTools: false,
      spellcheck: false,
    },
  });
  protectWindow(mainWindow);
  mainWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.loadURL(STUDIO_URL).catch(() => {});
  mainWindow.once("ready-to-show", () => showWindow());
}

async function gracefulShutdown() {
  if (healthTimer) clearInterval(healthTimer);
  if (ownsServer) {
    try {
      await requestStudio("/studio-api/quit", { method: "POST", timeout: 1500 });
    } catch (_error) {
      // The process is still terminated below; this is a best-effort flush.
    }
    if (serverProcess && !serverProcess.killed) {
      serverProcess.kill();
      serverProcess = null;
    }
  }
  if (tray) tray.destroy();
}

function registerIpc() {
  ipcMain.handle("window:show", () => showWindow());
  ipcMain.handle("window:hide", () => mainWindow?.hide());
  ipcMain.handle("engine:restart", async () => {
    await restartEngine();
    return true;
  });
  ipcMain.handle("server:state", () => studioHealth());
}

async function bootstrap() {
  const root = resolveMiroFishRoot();
  const alreadyRunning = await studioHealth();
  if (!alreadyRunning.online) {
    if (!root) throw new Error("找不到 MiroFish 安装目录。请设置 MIROFISH_ROOT，或使用完整安装包。");
    startStudioServer(root);
  }
  const state = await waitForStudio();
  if (!state.online) throw new Error("MiroFish Studio 未能在 3888 端口启动。");
  buildApplicationMenu();
  createTray();
  createWindow();
  healthTimer = setInterval(() => studioHealth().then(emitServerState), 5000);
  healthTimer.unref();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showWindow());
  app.whenReady().then(async () => {
    registerIpc();
    try {
      await bootstrap();
    } catch (error) {
      const message = error instanceof Error ? error.message : "MiroFish Studio 启动失败。";
      const { dialog } = require("electron");
      dialog.showErrorBox("MiroFish Studio", message);
      app.quit();
    }
  });
  app.on("activate", () => showWindow());
  app.on("before-quit", (event) => {
    if (isQuitting) return;
    isQuitting = true;
    event.preventDefault();
    gracefulShutdown().finally(() => app.exit(0));
  });
  app.on("window-all-closed", () => {
    // Keep the local controller available from the tray on Windows.
  });
}

