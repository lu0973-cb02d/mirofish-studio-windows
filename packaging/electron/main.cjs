const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const PORT = Number(process.env.MIROFISH_PORT || 3888);
let backend = null;

function runtimeRoot() {
  return process.env.MIROFISH_RUNTIME_ROOT || path.join(process.resourcesPath, 'runtime');
}
function pythonCandidates(root) {
  const bundled = process.platform === 'win32'
    ? [path.join(root, 'backend', '.venv', 'Scripts', 'pythonw.exe'), path.join(root, 'backend', '.venv', 'Scripts', 'python.exe')]
    : [path.join(root, 'backend', '.venv', 'bin', 'python')];
  return bundled.concat(process.platform === 'win32' ? ['pythonw.exe', 'python.exe'] : ['python3', 'python']);
}
function findPython(root) {
  return pythonCandidates(root).find(p => p.includes(path.sep) ? fs.existsSync(p) : true);
}
function healthCheck() {
  return new Promise(resolve => {
    const req = http.get(`http://127.0.0.1:${PORT}/studio-health`, res => { res.resume(); resolve(res.statusCode === 200); });
    req.on('error', () => resolve(false)); req.setTimeout(700, () => { req.destroy(); resolve(false); });
  });
}
async function waitForBackend() {
  for (let i = 0; i < 80; i += 1) { if (await healthCheck()) return true; await new Promise(r => setTimeout(r, 250)); }
  return false;
}
function startBackend() {
  const root = runtimeRoot();
  if (process.env.MIROFISH_CONTROL_PANEL === '1' && !process.env.MIROFISH_START_BACKEND) return null;
  const python = findPython(root);
  if (!python) throw new Error('未找到 Python 运行时。请安装 Python 3.11+，或使用全量安装版。');
  const env = { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' };
  return spawn(python, ['-m', 'local_studio.server', '--port', String(PORT)], { cwd: root, env, windowsHide: true, stdio: 'ignore' });
}
async function createWindow() {
  const win = new BrowserWindow({ width: 1440, height: 920, minWidth: 1024, minHeight: 700, autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true } });
  const url = process.env.MIROFISH_BACKEND_URL || `http://127.0.0.1:${PORT}/`;
  await win.loadURL(url);
  return win;
}
app.whenReady().then(async () => {
  try {
    backend = startBackend();
    if (backend) {
      if (!await waitForBackend()) throw new Error('MiroFish Studio 启动超时，请查看 studio_data/studio.log。');
    } else if (!await healthCheck() && !process.env.MIROFISH_BACKEND_URL) {
      throw new Error('控制面板版未找到运行中的 Studio。请先启动本地服务，或设置 MIROFISH_START_BACKEND=1。');
    }
    await createWindow();
  } catch (error) {
    dialog.showErrorBox('MiroFish 启动失败', error.message || String(error));
    app.quit();
  }
});
app.on('window-all-closed', () => { if (backend && !backend.killed) backend.kill(); if (process.platform !== 'darwin') app.quit(); });
