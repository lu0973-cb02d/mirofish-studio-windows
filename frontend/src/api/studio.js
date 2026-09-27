const API_ROOT = '/studio-api'

/** The local service owns credentials. Never persist keys in browser storage. */
async function request(path, { method = 'GET', body, signal, timeout = 30000 } = {}) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (signal?.aborted) abort()
  else signal?.addEventListener('abort', abort, { once: true })
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)

  try {
    const response = await fetch(`${API_ROOT}${path}`, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        'Accept': 'application/json',
        'X-MiroFish-Studio': '1',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' })
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal
    })
    let envelope
    try {
      envelope = await response.json()
    } catch {
      throw new Error('工作台没有返回有效结果，请稍后重试。')
    }
    if (!response.ok || envelope.success === false) {
      const detail = envelope.message || envelope.error?.message || envelope.error
      const error = new Error(typeof detail === 'string' ? detail : `操作未完成（${response.status}），请重试。`)
      error.status = response.status
      throw error
    }
    return envelope.data
  } catch (error) {
    if (timedOut) throw new Error('等待响应超时，请查看运行状态后重试。')
    if (error.name === 'AbortError') throw error
    if (error instanceof TypeError) throw new Error('暂时无法连接本地工作台，请确认工作台程序正在运行。')
    throw error
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}

const get = (path, signal) => request(path, { signal })
const post = (path, body, signal, timeout) => request(path, { method: 'POST', body, signal, timeout })
const remove = (path, signal) => request(path, { method: 'DELETE', signal })

export const studioApi = {
  config: signal => get('/config', signal),
  status: signal => get('/status', signal),
  records: signal => get('/records', signal),
  backups: signal => get('/backups', signal),
  logs: signal => get('/logs', signal),
  saveModel: (data, signal) => post('/models', data, signal),
  removeModel: (id, signal) => remove(`/models/${encodeURIComponent(id)}`, signal),
  activateModel: (id, signal) => post(`/models/${encodeURIComponent(id)}/activate`, {}, signal, 90000),
  discoverModels: (data, signal) => post('/models/discover', data, signal, 90000),
  testModel: (data, signal) => post('/models/test', data, signal, 90000),
  saveZep: (data, signal) => post('/zep', data, signal),
  removeZep: (id, signal) => remove(`/zep/${encodeURIComponent(id)}`, signal),
  activateZep: (id, signal) => post(`/zep/${encodeURIComponent(id)}/activate`, {}, signal, 90000),
  testZep: (data, signal) => post('/zep/test', data, signal, 90000),
  saveSettings: (data, signal) => post('/settings', data, signal),
  engine: (action, signal) => post(`/engine/${action}`, {}, signal, 90000),
  quit: signal => post('/quit', {}, signal, 90000),
  createBackup: signal => post('/backups/create', {}, signal, 300000),
  restoreBackup: (name, signal) => post('/backups/restore', { name }, signal, 300000)
}
