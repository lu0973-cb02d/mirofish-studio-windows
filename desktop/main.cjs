const { app, BrowserWindow, dialog, ipcMain, Menu, shell, Tray, nativeImage } = require('electron')
const fs = require('fs')
const fsp = fs.promises
const path = require('path')
const http = require('http')
const { spawn } = require('child_process')
const os = require('os')

const PRODUCT = 'MiroFish Studio'
const PORT = 3888
const LOCAL_URL = `http://127.0.0.1:${PORT}`
const ROOT_ARG = '--mirofish-root='
let windowRef = null
let tray = null
let runtimeProcess = null
let runtimeRoot = null
let runtimeDataRoot = null
let spawnedRuntime = false
let quitting = false

function packagedRoot() {
  const candidate = path.join(process.resourcesPath || '', 'mirofish')
  return fs.existsSync(path.join(candidate, 'local_studio')) ? candidate : null
}

function userConfigPath() { return path.join(app.getPath('userData'), 'desktop.json') }
function readConfig() {
  try { return JSON.parse(fs.readFileSync(userConfigPath(), 'utf8')) } catch { return {} }
}
function writeConfig(value) {
  fs.mkdirSync(path.dirname(userConfigPath()), { recursive: true })
  const temp = `${userConfigPath()}.${process.pid}.tmp`
  fs.writeFileSync(temp, JSON.stringify(value, null, 2), 'utf8')
  fs.renameSync(temp, userConfigPath())
}
function argumentRoot() {
  const arg = process.argv.find(value => value.startsWith(ROOT_ARG))
  return arg ? path.resolve(arg.slice(ROOT_ARG.length).replace(/^"|"$/g, '')) : ''
}
function validRoot(root) {
  return Boolean(root && fs.existsSync(path.join(root, 'local_studio', 'server.py')) && fs.existsSync(path.join(root, 'backend')))
}
function resolveRoot() {
  const explicit = argumentRoot() || process.env.MIROFISH_ROOT
  if (validRoot(explicit)) return path.resolve(explicit)
  const bundled = packagedRoot()
  // A full installation must be self-contained even when an earlier panel
  // installation saved a different working directory. An explicit CLI/env
  // root still wins so advanced users can point the panel at another checkout.
  if (validRoot(bundled)) return path.resolve(bundled)
  const configured = readConfig().root
  if (validRoot(configured)) return path.resolve(configured)
  const candidates = [
    path.resolve(__dirname, '..'),
    path.join(path.dirname(process.execPath), 'MiroFish'),
    path.join(process.env.USERPROFILE || '', 'MiroFish'),
    path.join(os.homedir(), 'Documents', 'MiroFish'),
    path.join(os.homedir(), 'OneDrive', '桌面', 'MiroFish')
  ]
  return candidates.find(validRoot) || ''
}
function pythonFor(root) {
  const candidates = [
    path.join(root, 'runtime', 'python.exe'),
    path.join(root, 'backend', '.venv', 'Scripts', 'pythonw.exe'),
    path.join(root, 'backend', '.venv', 'Scripts', 'python.exe'),
    path.join(root, 'python', 'python.exe')
  ]
  return candidates.find(fs.existsSync) || ''
}
function fetchJson(url, options = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { ...options, timeout: options.timeout || 1000, headers: options.headers || {} }, res => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', chunk => { body += chunk })
      res.on('end', () => { try { resolve({ status: res.statusCode, data: JSON.parse(body || '{}') }) } catch { resolve({ status: res.statusCode, data: {} }) } })
    })
    req.on('timeout', () => req.destroy(new Error('timeout')))
    req.on('error', reject)
    if (options.body) req.write(options.body)
    req.end()
  })
}
async function health() {
  try { const result = await fetchJson(`${LOCAL_URL}/studio-health`); return result.status === 200 && result.data?.service === PRODUCT } catch { return false }
}
async function startRuntime(root) {
  runtimeRoot = path.resolve(root)
  runtimeDataRoot = packagedRoot()
    ? path.join(app.getPath('userData'), 'data')
    : runtimeRoot
  fs.mkdirSync(runtimeDataRoot, { recursive: true })
  if (await health()) return { ok: true, reused: true }
  const python = pythonFor(runtimeRoot)
  if (!python) return { ok: false, error: '没有找到 MiroFish 运行环境。请先安装全量版，或选择已有的 MiroFish 工作目录。' }
  const frontendRoot = app.isPackaged && !packagedRoot()
    ? path.join(process.resourcesPath, 'frontend', 'dist')
    : ''
  const env = { ...process.env, MIROFISH_STUDIO_ROOT: runtimeRoot, MIROFISH_DATA_ROOT: runtimeDataRoot, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONPATH: runtimeRoot }
  if (frontendRoot && fs.existsSync(path.join(frontendRoot, 'index.html'))) env.MIROFISH_STUDIO_FRONTEND_ROOT = frontendRoot
  const logDir = path.join(runtimeDataRoot, 'studio_data')
  fs.mkdirSync(logDir, { recursive: true })
  const log = fs.openSync(path.join(logDir, 'desktop.log'), 'a')
  runtimeProcess = spawn(python, ['-m', 'local_studio.server'], { cwd: runtimeRoot, env, detached: false, windowsHide: true, stdio: ['ignore', log, log] })
  spawnedRuntime = true
  runtimeProcess.once('exit', () => { runtimeProcess = null; spawnedRuntime = false })
  for (let i = 0; i < 60; i += 1) { if (await health()) return { ok: true, reused: false }; await new Promise(r => setTimeout(r, 500)) }
  return { ok: false, error: 'MiroFish 工作台启动超时，请查看 studio_data/desktop.log。' }
}
async function closeRuntime() {
  if (!spawnedRuntime) return
  try { await fetchJson(`${LOCAL_URL}/studio-api/quit`, { method: 'POST', timeout: 2000, headers: { 'X-MiroFish-Studio': '1', 'Content-Type': 'application/json' }, body: '{}' }) } catch {}
  if (runtimeProcess) { try { runtimeProcess.kill() } catch {} }
  runtimeProcess = null; spawnedRuntime = false
}
function iconPath() {
  const candidates = [
    path.join(process.resourcesPath || '', 'mirofish-logo.ico'),
    path.join(__dirname, 'assets', 'mirofish.ico'),
    path.join(path.resolve(__dirname, '..'), 'packaging', 'assets', 'mirofish-logo.ico')
  ]
  return candidates.find(fs.existsSync) || candidates[0]
}
function createWindow() {
  windowRef = new BrowserWindow({ width: 1440, height: 940, minWidth: 1000, minHeight: 680, show: false, title: PRODUCT, icon: iconPath(), backgroundColor: '#f6f7f5', autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: false, spellcheck: false } })
  windowRef.webContents.setWindowOpenHandler(({ url }) => ({ action: url.startsWith(LOCAL_URL) ? 'allow' : 'deny' }))
  windowRef.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(LOCAL_URL)) event.preventDefault() })
  windowRef.webContents.on('will-attach-webview', event => { event.preventDefault() })
  windowRef.webContents.on('before-input-event', (event, input) => { const key = String(input.key || '').toLowerCase(); if (key === 'f12' || (input.control && input.shift && key === 'i')) event.preventDefault() })
  windowRef.on('close', event => { if (!quitting) { event.preventDefault(); windowRef.hide() } })
  windowRef.once('ready-to-show', () => windowRef.show())
  return windowRef
}
async function showWindow() { if (windowRef) { windowRef.show(); windowRef.focus() } }
async function showSetup() { if (!windowRef) createWindow(); await windowRef.loadFile(path.join(__dirname, 'setup.html')) }
async function openWorkspace() { if (!windowRef) createWindow(); await windowRef.loadURL(LOCAL_URL) }
function buildTray() {
  if (tray) return
  const image = nativeImage.createFromPath(iconPath())
  tray = new Tray(image.isEmpty() ? nativeImage.createEmpty() : image)
  tray.setToolTip(PRODUCT)
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开工作台', click: showWindow },
    { type: 'separator' },
    { label: '重启推演引擎', click: async () => { await fetchJson(`${LOCAL_URL}/studio-api/engine/restart`, { method: 'POST', headers: { 'X-MiroFish-Studio': '1', 'Content-Type': 'application/json' }, body: '{}' }); showWindow() } },
    { label: '打开数据目录', click: () => runtimeDataRoot && shell.openPath(runtimeDataRoot) },
    { type: 'separator' },
    { label: '退出 MiroFish Studio', click: async () => { quitting = true; await closeRuntime(); app.quit() } }
  ]))
  tray.on('double-click', showWindow)
}
async function selectRoot() { const result = await dialog.showOpenDialog(windowRef, { title: '选择 MiroFish 工作目录', properties: ['openDirectory'] }); return result.canceled ? '' : result.filePaths[0] }
ipcMain.handle('desktop:get-status', async () => ({ root: runtimeRoot || resolveRoot(), ready: validRoot(runtimeRoot || resolveRoot()), running: await health() }))
ipcMain.handle('desktop:choose-root', async () => { const root = await selectRoot(); return root ? { root, ready: validRoot(root) } : {} })
ipcMain.handle('desktop:set-root', async (_event, root) => { if (!validRoot(root)) return { ok: false, error: '该目录不像 MiroFish 工作目录，请选择包含 backend 和 local_studio 的文件夹。' }; writeConfig({ root: path.resolve(root) }); const result = await startRuntime(root); if (result.ok) await openWorkspace(); return result })
ipcMain.handle('desktop:restart-engine', async () => fetchJson(`${LOCAL_URL}/studio-api/engine/restart`, { method: 'POST', headers: { 'X-MiroFish-Studio': '1', 'Content-Type': 'application/json' }, body: '{}' }))
ipcMain.handle('desktop:open-data-folder', () => runtimeDataRoot ? shell.openPath(runtimeDataRoot) : undefined)
ipcMain.handle('desktop:open-guide', () => shell.openPath(path.join(runtimeRoot || '', 'STUDIO_README.md')))
ipcMain.handle('desktop:show-window', showWindow)
ipcMain.handle('desktop:quit', async () => { quitting = true; await closeRuntime(); app.quit() })
async function main() {
  const gotLock = app.requestSingleInstanceLock()
  if (!gotLock) return app.quit()
  app.on('second-instance', showWindow)
  await app.whenReady()
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: PRODUCT, submenu: [{ label: '刷新工作台', accelerator: 'CmdOrCtrl+R', click: () => windowRef?.reload() }, { type: 'separator' }, { label: '退出', click: async () => { quitting = true; await closeRuntime(); app.quit() } }] }]))
  buildTray(); createWindow()
  const root = resolveRoot()
  const result = root ? await startRuntime(root) : { ok: false }
  if (result.ok) { writeConfig({ root }); await openWorkspace() } else await showSetup()
}
app.on('window-all-closed', event => event.preventDefault())
app.on('before-quit', async event => { if (!quitting) { event.preventDefault(); quitting = true; await closeRuntime(); app.quit() } })
main().catch(error => dialog.showErrorBox(PRODUCT, error.message || '桌面工作台启动失败'))
