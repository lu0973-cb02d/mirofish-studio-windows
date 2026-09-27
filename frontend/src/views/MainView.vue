<template>
  <div class="main-view">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <router-link class="brand" to="/">MiroFish <span>Studio</span></router-link>
      </div>
      
      <div class="header-center">
        <div class="view-switcher">
          <button 
            v-for="mode in ['graph', 'split', 'workbench']" 
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{ { graph: '图谱', split: '并排查看', workbench: '进度详情' }[mode] }}
          </button>
        </div>
      </div>

      <div class="header-right">
        <LanguageSwitcher />
        <div class="step-divider"></div>
        <div class="workflow-step">
          <span class="step-num">第 {{ currentStep }}/5 步</span>
          <span class="step-name">{{ stepNames[currentStep - 1] }}</span>
        </div>
        <div class="step-divider"></div>
        <span class="status-indicator" :class="statusClass">
          <span class="dot"></span>
          {{ statusText }}
        </span>
      </div>
    </header>

    <section v-if="error || connectionWarning || needsGraphStart" class="recovery-panel" :class="{ 'is-error': error && !connectionWarning }" :role="error || connectionWarning ? 'alert' : 'status'">
      <div class="recovery-copy">
        <h2>{{ connectionWarning ? '进度暂时无法确认' : error ? '当前步骤需要处理' : '材料分析已完成' }}</h2>
        <p>{{ connectionWarning || error || '已保存材料和分析结果。准备好后，点击开始构建图谱。' }}</p>
        <p class="recovery-note">{{ recoveryHint }}</p>
      </div>
      <div class="recovery-actions">
        <button v-if="currentProjectId !== 'new'" :disabled="loading || buildSubmitting" @click="recoverView">{{ loading ? '正在读取…' : '恢复查看' }}</button>
        <button v-if="canRetryGraph" class="recovery-primary" :disabled="loading || buildSubmitting" @click="startBuildGraph">{{ buildSubmitting ? '正在提交…' : needsGraphStart ? '开始构建图谱' : '重试图谱构建' }}</button>
        <button v-if="canRetryUpload" class="recovery-primary" :disabled="loading || buildSubmitting" @click="handleNewProject">{{ loading ? '正在提交…' : '重新提交材料' }}</button>
        <router-link v-if="uploadFailed || currentProjectId === 'new'" to="/?tab=records">查看已保存项目</router-link>
        <router-link v-if="uploadFailed || currentProjectId === 'new' || (error && !projectData?.ontology)" to="/new">返回新建</router-link>
      </div>
    </section>

    <!-- Main Content Area -->
    <main class="content-area">
      <!-- Left Panel: Graph -->
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <GraphPanel 
          :graphData="graphData"
          :loading="graphLoading"
          :currentPhase="currentPhase"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <!-- Right Panel: Step Components -->
      <div class="panel-wrapper right" :style="rightPanelStyle">
        <!-- Step 1: 图谱构建 -->
        <Step1GraphBuild 
          v-if="currentStep === 1"
          :currentPhase="currentPhase"
          :projectData="projectData"
          :ontologyProgress="ontologyProgress"
          :buildProgress="buildProgress"
          :graphData="graphData"
          :systemLogs="systemLogs"
          :taskError="error"
          :connectionWarning="connectionWarning"
          :busy="loading || buildSubmitting"
          @next-step="handleNextStep"
        />
        <!-- Step 2: 环境搭建 -->
        <Step2EnvSetup
          v-else-if="currentStep === 2"
          :projectData="projectData"
          :graphData="graphData"
          :systemLogs="systemLogs"
          @go-back="handleGoBack"
          @next-step="handleNextStep"
          @add-log="addLog"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import GraphPanel from '../components/GraphPanel.vue'
import Step1GraphBuild from '../components/Step1GraphBuild.vue'
import Step2EnvSetup from '../components/Step2EnvSetup.vue'
import { generateOntology, getProject, buildGraph, getTaskStatus, getGraphData } from '../api/graph'
import { getPendingUpload, clearPendingUpload } from '../store/pendingUpload'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// Layout State
const viewMode = ref('split') // graph | split | workbench

// Step State
const currentStep = ref(1) // 1: 图谱构建, 2: 环境搭建, 3: 开始模拟, 4: 报告生成, 5: 深度互动
const stepNames = ['图谱构建', '环境搭建', '双线推演', '结果报告', '深度互动']

// Data State
const currentProjectId = ref(route.params.projectId)
const loading = ref(false)
const graphLoading = ref(false)
const error = ref('')
const readErrors = reactive({ project: '', task: '', graph: '' })
const connectionWarning = computed(() => readErrors.project || readErrors.task || readErrors.graph)
const buildSubmitting = ref(false)
const uploadFailed = ref(false)
const taskUnavailable = ref(false)
const projectData = ref(null)
const graphData = ref(null)
const currentPhase = ref(-1) // -1: Upload, 0: Ontology, 1: Build, 2: Complete
const ontologyProgress = ref(null)
const buildProgress = ref(null)
const systemLogs = ref([])

// Polling timers
let pollTimer = null
let graphPollTimer = null
let pollGeneration = 0
let graphPollGeneration = 0
let disposed = false

const needsGraphStart = computed(() => !error.value && !connectionWarning.value && !buildSubmitting.value && projectData.value?.status === 'ontology_generated')
const canRetryGraph = computed(() => Boolean(projectData.value?.ontology && currentProjectId.value !== 'new' && (!connectionWarning.value || taskUnavailable.value) && (['ontology_generated', 'failed'].includes(projectData.value.status) || taskUnavailable.value)))
const canRetryUpload = computed(() => uploadFailed.value && getPendingUpload().isPending && getPendingUpload().files.length > 0)
const recoveryHint = computed(() => {
  if (uploadFailed.value) return canRetryUpload.value ? '待上传材料仍保留在当前页面。若上次响应中断，请先查看已保存项目；重新提交会启动一次新的材料分析。' : '当前页面没有待上传材料，请返回新建页面重新选择。'
  if (taskUnavailable.value) return '暂时无法确认原任务是否仍在运行。恢复查看只读取记录，不会自动重新构建。'
  if (readErrors.task) return '页面会继续尝试读取进度；恢复查看只读取已保存的记录，不会重新提交任务。'
  if (connectionWarning.value) return '已显示的内容会保留。恢复查看只读取已保存的记录，不会重新提交任务。'
  if (error.value) return '已保存的项目仍然保留。恢复查看可以重新读取状态，重试构建由你手动决定。'
  return '恢复查看不会自动开始新任务。'
})

// --- Computed Layout Styles ---
const leftPanelStyle = computed(() => {
  if (viewMode.value === 'graph') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'workbench') return { width: '0%', opacity: 0, transform: 'translateX(-20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'workbench') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'graph') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

// --- Status Computed ---
const statusClass = computed(() => {
  if (connectionWarning.value) return 'disconnected'
  if (error.value) return 'error'
  if (currentPhase.value >= 2) return 'completed'
  return 'processing'
})

const statusText = computed(() => {
  if (connectionWarning.value) return '状态待确认'
  if (error.value) return '需要处理'
  if (currentPhase.value >= 2) return '图谱已就绪'
  if (buildSubmitting.value) return '正在提交构建'
  if (needsGraphStart.value) return '等待开始构图'
  if (currentPhase.value === 1) return '正在构建图谱'
  if (currentPhase.value === 0) return '正在分析材料'
  return loading.value ? '正在读取项目' : '等待材料'
})

// --- Helpers ---
const addLog = (msg) => {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + new Date().getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg })
  // Keep last 100 logs
  if (systemLogs.value.length > 100) {
    systemLogs.value.shift()
  }
}

// --- Layout Methods ---
const toggleMaximize = (target) => {
  if (viewMode.value === target) {
    viewMode.value = 'split'
  } else {
    viewMode.value = target
  }
}

const handleNextStep = (params = {}) => {
  if (currentStep.value < 5) {
    currentStep.value++
    addLog(t('log.enterStep', { step: currentStep.value, name: stepNames[currentStep.value - 1] }))
    
    // 如果是从 Step 2 进入 Step 3，记录模拟轮数配置
    if (currentStep.value === 3 && params.maxRounds) {
      addLog(t('log.customSimRounds', { rounds: params.maxRounds }))
    }
  }
}

const handleGoBack = () => {
  if (currentStep.value > 1) {
    currentStep.value--
    addLog(t('log.returnToStep', { step: currentStep.value, name: stepNames[currentStep.value - 1] }))
  }
}

// --- Data Logic ---
// Only explicit user actions submit work. Loading a saved project only reads state.
const readableError = (value, fallback) => {
  const message = typeof value === 'string' ? value : value?.message || ''
  if (/401|invalid.?api.?key|authentication/i.test(message)) return '连接密钥未通过验证，请在工作台检查对应的 API Key。'
  if (/403|permission|forbidden/i.test(message)) return '当前连接没有访问权限，请检查连接配置及所属项目。'
  if (/429|quota|rate.?limit/i.test(message)) return '服务额度或请求频率受限，请检查可用连接后再重试。'
  if (/[\u3400-\u9fff]/.test(message)) return message
  return fallback
}

const clearReadErrors = () => {
  readErrors.project = ''
  readErrors.task = ''
  readErrors.graph = ''
}

const initProject = async () => {
  addLog('正在打开项目。')
  if (currentProjectId.value === 'new') await handleNewProject()
  else await loadProject()
}

const handleNewProject = async () => {
  if (loading.value || buildSubmitting.value || disposed) return
  const pending = getPendingUpload()
  if (!pending.isPending || !pending.files.length) {
    uploadFailed.value = true
    error.value = '当前页面没有待上传的材料。请返回新建页面重新选择文件或填写背景文字。'
    currentPhase.value = -1
    return
  }

  loading.value = true
  error.value = ''
  uploadFailed.value = false
  taskUnavailable.value = false
  clearReadErrors()
  stopPolling()
  stopGraphPolling()
  currentPhase.value = 0
  ontologyProgress.value = { message: '正在上传材料并分析角色与关系，请稍候…' }
  addLog('开始上传与分析材料。')
  try {
    const formData = new FormData()
    pending.files.forEach(file => formData.append('files', file))
    formData.append('simulation_requirement', pending.simulationRequirement)
    formData.append('project_name', pending.projectName || pending.simulationRequirement.slice(0, 30) || '新的推演')
    const res = await generateOntology(formData)
    if (disposed) return
    if (!res.success || !res.data?.project_id) throw new Error(res.error || '分析结果暂未返回。')

    currentProjectId.value = res.data.project_id
    projectData.value = { ...res.data, status: 'ontology_generated' }
    clearPendingUpload()
    await router.replace({ name: 'Process', params: { projectId: currentProjectId.value } })
    ontologyProgress.value = null
    addLog('材料分析完成，已保存项目。')
    // This is the initial explicitly requested new-project flow.
    await startBuildGraph()
  } catch (err) {
    if (disposed) return
    uploadFailed.value = true
    const savedProjectId = err.response?.data?.data?.project_id
    const outcomeUnknown = !err.response || (err.response.status >= 502 && !savedProjectId)
    if (outcomeUnknown) {
      readErrors.project = '没有收到材料分析的完整结果，后台可能仍在处理。请先查看已保存项目，避免重复提交。'
    } else {
      error.value = readableError(err, '材料分析没有完成。请检查模型连接后，手动重新提交。')
    }
    addLog('材料分析未返回成功结果：' + (err.message || '未提供原因'))
    if (savedProjectId) {
      currentProjectId.value = savedProjectId
      await router.replace({ name: 'Process', params: { projectId: savedProjectId } })
      try {
        const saved = await getProject(savedProjectId)
        if (!disposed && saved.success) projectData.value = saved.data
      } catch { /* Keep the original error and pending files for an explicit retry. */ }
    }
  } finally {
    if (!disposed) {
      loading.value = false
      ontologyProgress.value = null
    }
  }
}

const loadProject = async () => {
  if (disposed || currentProjectId.value === 'new') return false
  loading.value = true
  stopPolling()
  stopGraphPolling()
  clearReadErrors()
  taskUnavailable.value = false
  try {
    const res = await getProject(currentProjectId.value)
    if (disposed) return false
    if (!res.success || !res.data) throw new Error(res.error || '无法读取项目。')
    projectData.value = res.data
    error.value = ''
    ontologyProgress.value = null
    updatePhaseByStatus(res.data.status)
    addLog('已读取保存的项目状态：' + res.data.status)

    if (res.data.status === 'graph_building') {
      if (res.data.graph_build_task_id) startPollingTask(res.data.graph_build_task_id)
      else {
        taskUnavailable.value = true
        readErrors.task = '项目仍保留构建记录，但暂时找不到对应任务。可以恢复查看，或手动重试构建。'
      }
    } else if (res.data.status === 'graph_completed' && res.data.graph_id) {
      buildProgress.value = { progress: 100, message: '图谱构建已完成。' }
      await loadGraph(res.data.graph_id)
    } else if (res.data.status === 'graph_completed') {
      readErrors.project = '项目显示已完成，但图谱信息暂时无法读取，请恢复查看。'
    } else if (res.data.status === 'created') {
      readErrors.project = '还未读取到材料分析结果。若刚刚提交过材料，请稍后恢复查看。'
    }
    // ontology_generated is intentionally left waiting for an explicit build.
    return true
  } catch (err) {
    if (!disposed) {
      readErrors.project = readableError(err, '暂时无法读取已保存的项目。请确认引擎正在运行，然后恢复查看。')
      addLog('读取项目状态未成功：' + (err.message || '连接中断'))
    }
    return false
  } finally {
    if (!disposed) loading.value = false
  }
}

const recoverView = async () => {
  if (loading.value || buildSubmitting.value) return
  await loadProject()
}

const updatePhaseByStatus = (status) => {
  switch (status) {
    case 'created':
    case 'ontology_generated':
      currentPhase.value = 0
      buildProgress.value = null
      break
    case 'graph_building':
      currentPhase.value = 1
      break
    case 'graph_completed':
      currentPhase.value = 2
      break
    case 'failed':
      currentPhase.value = projectData.value?.ontology ? 1 : 0
      error.value = readableError(projectData.value?.error, projectData.value?.ontology ? '图谱构建未完成，请检查 Zep 连接后手动重试。' : '材料分析未完成，请检查模型配置。')
      break
    default:
      currentPhase.value = -1
  }
}

const startBuildGraph = async () => {
  if (buildSubmitting.value || disposed || currentProjectId.value === 'new') return
  buildSubmitting.value = true
  error.value = ''
  clearReadErrors()
  taskUnavailable.value = false
  stopPolling()
  stopGraphPolling()
  currentPhase.value = 1
  buildProgress.value = { progress: 0, message: '正在提交图谱构建请求…' }
  addLog('提交图谱构建请求，优先复用已有任务与图谱。')
  try {
    // Never force a rebuild on page recovery or on an ordinary retry.
    const res = await buildGraph({ project_id: currentProjectId.value })
    if (disposed) return
    if (!res.success) throw new Error(res.error || '构建请求没有成功。')

    // reused + graph_id may also describe an active build. Persisted status is
    // the authority; a graph ID alone never means the build has completed.
    const restored = await loadProject()
    if (!restored && res.data?.task_id && !disposed) startPollingTask(res.data.task_id)
  } catch (err) {
    if (disposed) return
    const outcomeUnknown = !err.response || err.response.status >= 502
    if (outcomeUnknown) {
      readErrors.project = '构建请求的结果尚未确认。请恢复查看已保存的任务，页面不会自动再次提交。'
    } else {
      error.value = readableError(err, '图谱构建请求未成功，请检查 Zep 连接后再手动重试。')
      if (err.response?.status === 409) taskUnavailable.value = true
    }
    addLog('构建请求未返回成功结果：' + (err.message || '未提供原因'))
  } finally {
    if (!disposed) buildSubmitting.value = false
  }
}

const startGraphPolling = () => {
  stopGraphPolling()
  const generation = graphPollGeneration
  const tick = async () => {
    await fetchGraphData(generation)
    if (!disposed && generation === graphPollGeneration) graphPollTimer = setTimeout(tick, 10000)
  }
  tick()
}

const fetchGraphData = async (generation) => {
  try {
    const projRes = await getProject(currentProjectId.value)
    if (disposed || generation !== graphPollGeneration) return
    if (!projRes.success) throw new Error(projRes.error || '无法读取图谱状态。')
    if (projRes.data?.graph_id) {
      const res = await getGraphData(projRes.data.graph_id)
      if (disposed || generation !== graphPollGeneration) return
      if (!res.success) throw new Error(res.error || '无法读取图谱。')
      graphData.value = res.data
    }
    readErrors.graph = ''
  } catch (err) {
    if (!disposed && generation === graphPollGeneration) readErrors.graph = '图谱预览暂时无法刷新，已显示的内容会保留。后台任务状态将继续查询。'
  }
}

const startPollingTask = (taskId) => {
  if (!taskId || disposed) return
  stopPolling()
  startGraphPolling()
  const generation = pollGeneration
  const tick = async () => {
    await pollTaskStatus(taskId, generation)
    if (!disposed && generation === pollGeneration) pollTimer = setTimeout(tick, 2000)
  }
  tick()
}

const progressMessage = (task) => {
  if (task.status === 'completed') return '图谱构建已完成。'
  if (task.status === 'pending') return '构建请求已接收，正在准备。'
  const progress = Number(task.progress) || 0
  if (progress < 5) return '正在准备图谱服务…'
  if (progress < 10) return '正在整理背景材料…'
  if (progress < 15) return '正在创建记忆图谱…'
  if (progress < 55) return '正在导入材料与关系定义…'
  if (progress < 95) return '正在处理材料，生成角色与关系…'
  return '正在整理图谱结果，即将完成…'
}

const pollTaskStatus = async (taskId, generation) => {
  try {
    const res = await getTaskStatus(taskId)
    if (disposed || generation !== pollGeneration) return
    if (!res.success || !res.data) throw new Error(res.error || '无法读取任务进度。')
    const task = res.data
    readErrors.task = ''
    taskUnavailable.value = false
    if (task.message && task.message !== buildProgress.value?.originalMessage) addLog(task.message)
    buildProgress.value = {
      progress: Math.min(100, Math.max(0, Number(task.progress) || 0)),
      message: progressMessage(task),
      originalMessage: task.message
    }

    if (task.status === 'completed') {
      stopPolling()
      stopGraphPolling()
      addLog('图谱构建任务已完成，正在读取保存结果。')
      await loadProject()
    } else if (task.status === 'failed') {
      stopPolling()
      stopGraphPolling()
      clearReadErrors()
      error.value = readableError(task.error, '图谱构建未完成。项目材料仍保留，可以检查 Zep 连接后手动重试。')
      if (projectData.value) projectData.value = { ...projectData.value, status: 'failed', error: task.error }
      addLog('图谱任务返回失败：' + (task.error || '未提供详细原因'))
    }
  } catch (err) {
    if (disposed || generation !== pollGeneration) return
    if (err.response?.status === 404) {
      stopPolling()
      stopGraphPolling()
      taskUnavailable.value = true
      readErrors.task = '当前任务记录已无法读取。项目仍保留，请先恢复查看保存状态；需要重新构建时再手动重试。'
    } else {
      // A failed read is not a failed task and never triggers a write request.
      readErrors.task = '暂时无法读取最新任务进度，正在自动重连。后台任务可能仍在继续。'
    }
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  try {
    const res = await getGraphData(graphId)
    if (disposed) return
    if (!res.success) throw new Error(res.error || '无法读取图谱。')
    graphData.value = res.data
    readErrors.graph = ''
    addLog('已读取图谱结果。')
  } catch (err) {
    if (!disposed) readErrors.graph = readableError(err, '图谱已构建，但预览暂时无法读取。可以恢复查看，无需重新构建。')
  } finally {
    if (!disposed) graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) loadGraph(projectData.value.graph_id)
  else if (!loading.value && currentProjectId.value !== 'new') recoverView()
}

const stopPolling = () => {
  pollGeneration += 1
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

const stopGraphPolling = () => {
  graphPollGeneration += 1
  if (graphPollTimer) clearTimeout(graphPollTimer)
  graphPollTimer = null
}

onMounted(() => {
  initProject()
})

onUnmounted(() => { disposed = true
  stopPolling()
  stopGraphPolling()
})
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FFF;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

/* Header */
.app-header {
  flex-shrink: 0;
  height: 60px;
  border-bottom: 1px solid #EAEAEA;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #FFF;
  z-index: 100;
  position: relative;
}

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}

.view-switcher {
  display: flex;
  background: #F5F5F5;
  padding: 4px;
  border-radius: 6px;
  gap: 4px;
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.switch-btn.active {
  background: #FFF;
  color: #000;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #999;
}

.step-name {
  font-weight: 700;
  color: #000;
}

.step-divider {
  width: 1px;
  height: 14px;
  background-color: #E0E0E0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #CCC;
}

.status-indicator.processing .dot { background: #FF5722; animation: pulse 1s infinite; }
.status-indicator.completed .dot { background: #4CAF50; }
.status-indicator.error .dot { background: #F44336; }
.status-indicator.disconnected .dot { background: #ba812b; }

.recovery-panel { flex-shrink: 0; display: flex; align-items: center; gap: 24px; padding: 17px 24px; border-bottom: 1px solid #e5d9b8; background: #fff8e9; color: #796029; max-height: 245px; overflow-y: auto; }
.recovery-panel.is-error { background: #fff0eb; border-color: #e8cbbf; color: #923e30; }
.recovery-copy { flex: 1; min-width: 0; }
.recovery-copy h2 { font-size: 15px; line-height: 1.5; margin: 0 0 4px; font-weight: 650; }
.recovery-copy p { font-size: 13px; line-height: 1.75; margin: 0; overflow-wrap: anywhere; }
.recovery-copy .recovery-note { font-size: 12px; margin-top: 5px; color: #706a5c; }
.recovery-actions { display: flex; flex-wrap: wrap; gap: 9px; align-items: center; justify-content: flex-end; max-width: 460px; }
.recovery-actions button, .recovery-actions a { min-height: 39px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #d9dfd2; background: white; color: #425b48; border-radius: 7px; padding: 9px 13px; text-decoration: none; font-family: inherit; font-size: 12px; line-height: 1.5; white-space: nowrap; cursor: pointer; }
.recovery-actions .recovery-primary { background: #147d64; border-color: #147d64; color: white; }
.recovery-actions button:disabled { opacity: .5; cursor: wait; }
.recovery-actions :is(button, a):focus-visible { outline: 3px solid #79b09a; outline-offset: 3px; }
@media (max-width: 900px) { .recovery-panel { flex-direction: column; align-items: stretch; gap: 12px; padding: 15px 19px; } .recovery-actions { justify-content: flex-start; max-width: none; } }
@media (prefers-reduced-motion: reduce) { .status-indicator.processing .dot { animation: none; } .panel-wrapper { transition: none !important; } }

@keyframes pulse { 50% { opacity: 0.5; } }

/* Content */
.content-area {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
  overflow: hidden;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1), opacity 0.3s ease, transform 0.3s ease;
  will-change: width, opacity, transform;
}

.panel-wrapper.left {
  border-right: 1px solid #EAEAEA;
}
</style>
