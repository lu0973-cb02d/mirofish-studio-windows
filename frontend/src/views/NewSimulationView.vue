<template>
  <div class="new-workspace">
    <header><RouterLink to="/" class="brand"><img src="/icon.png" alt="" />MiroFish <span>Studio</span></RouterLink><RouterLink to="/" class="back-link"><Icon name="arrow" />返回工作台</RouterLink></header>
    <main>
      <div class="intro"><span class="eyebrow">NEW SIMULATION</span><h1>创建新的推演</h1><p>整理背景材料，写下要探索的问题。准备好之后，开始构建你的模拟世界。</p></div>
      <div class="create-grid">
        <form @submit.prevent="submit">
          <section class="name-section"><label for="project-name">推演名称 <span class="optional">选填</span></label><input id="project-name" v-model.trim="name" maxlength="100" placeholder="起一个容易找到的名字；留空会取目标的前 30 字" /></section>
          <section><div class="section-heading"><span class="number">01</span><div><h2>放入背景材料</h2><p>直接粘贴文字，也可以上传文档，两种方式可同时使用。</p></div></div>
            <label for="seed">背景文字 <span class="optional">选填</span></label>
            <textarea id="seed" v-model="seed" rows="7" placeholder="描述真实的起点：参与者、当前情况、发生过的事情，以及你已经知道的信息。" maxlength="200000"></textarea>
            <div class="field-meta"><span>支持文字与文档一起使用</span><span>{{ seed.length.toLocaleString() }} / 200,000</span></div>
            <div class="dropzone" :class="{ over: dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
              <svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4"/></svg>
              <div><strong>拖入文档，或 <button type="button" class="text-button" @click="input?.click()">选择文件</button></strong><p>PDF、TXT、Markdown · 合计不超过 50 MB</p></div>
              <input ref="input" type="file" accept=".pdf,.txt,.md,.markdown" multiple hidden @change="selectFiles" />
            </div>
            <TransitionGroup name="file-item" tag="ul" class="files"><li v-for="(file, i) in files" :key="file.name + file.size"><Icon name="file" /><span>{{ file.name }}</span><small>{{ formatSize(file.size) }}</small><button type="button" :aria-label="`移除 ${file.name}`" @click="files.splice(i,1)"><Icon name="close" /></button></li></TransitionGroup>
          </section>
          <section><div class="section-heading"><span class="number">02</span><div><h2>说清楚推演目标</h2><p>聚焦一个核心问题，后续还可以设置轮数与角色。</p></div></div>
            <label for="requirement">你想推演什么？</label>
            <textarea id="requirement" v-model="requirement" rows="5" required maxlength="15000" placeholder="例如：如果这项产品调整正式上线，不同用户群体会如何反应？哪些条件下可能出现另一种结果？"></textarea>
            <div class="tip">把已知事实放在材料里，把假设写在目标里，能让结果更容易理解和比较。</div>
          </section>
          <Transition name="feedback"><div v-if="error" class="error" role="alert"><Icon name="info" />{{ error }}</div></Transition>
          <div class="submit-row"><span>结果供探索与比较使用，不代表确定预测。</span><button type="submit" class="primary" :disabled="!canSubmit || submitting || !engineReady"><Icon :name="submitting ? 'loader' : 'spark'" :class="{ spinning: submitting }" />{{ submitting ? '正在进入…' : '开始构建推演' }}<Icon v-if="!submitting" name="arrow" /></button></div>
        </form>
        <aside>
          <div class="connection"><span class="eyebrow">本次使用</span><h3>{{ status?.active_model?.name || '尚未选择模型' }}</h3><p class="model-name">{{ status?.active_model?.model || '返回工作台配置连接' }}</p><div class="badge" :class="{ ready: engineReady }">{{ engineReady ? '引擎已就绪' : '引擎未就绪' }}</div><p v-if="!engineReady">请先回工作台确认连接与运行状态。已填写的文字会保留。</p><RouterLink to="/">管理连接与服务 ↗</RouterLink></div>
          <div class="journey"><h3>接下来会发生什么</h3><ol><li><strong>建立图谱</strong><span>从材料中提取角色与关系</span></li><li><strong>设定世界</strong><span>检查人设、平台与推演轮数</span></li><li><strong>运行推演</strong><span>观察两条线的行动和变化</span></li><li><strong>生成报告</strong><span>结合图谱与采访整理发现</span></li></ol><p>关闭窗口会收至托盘，后台任务继续运行。完成后可以从工作台的记录继续查看。</p></div>
        </aside>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, toRef, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { setPendingUpload, newProjectDraft } from '../store/pendingUpload'
import Icon from '../components/studio/StudioIcon.vue'

const router = useRouter()
const seed = toRef(newProjectDraft, 'seed'), requirement = toRef(newProjectDraft, 'requirement')
const files = toRef(newProjectDraft, 'files'), name = toRef(newProjectDraft, 'name'), input = ref(null)
const dragging = ref(false), error = ref(''), submitting = ref(false), status = ref(null)
const engineReady = computed(() => !!status.value?.engine?.healthy && status.value.engine.configuration_synced !== false)
const maxSize = 50 * 1024 * 1024
const canSubmit = computed(() => requirement.value.trim() && (seed.value.trim() || files.value.length))
const formatSize = value => value < 1024 * 1024 ? `${Math.ceil(value / 1024)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`
const add = list => {
  error.value = ''
  for (const f of list) {
    if (!/\.(pdf|txt|md|markdown)$/i.test(f.name)) { error.value = '只支持 PDF、TXT 和 Markdown 文档。'; continue }
    if (files.value.some(old => old.name === f.name && old.size === f.size)) continue
    if (files.value.length >= 20 || files.value.reduce((s,v) => s+v.size, 0) + f.size > maxSize) { error.value = '最多 20 份材料，合计不能超过 50 MB。'; break }
    files.value.push(f)
  }
}
const selectFiles = e => { add(Array.from(e.target.files)); e.target.value = '' }
const drop = e => { dragging.value = false; add(Array.from(e.dataTransfer.files)) }
let statusTimer = null, closed = false
const refreshStatus = async () => {
  try { const r = await fetch('/studio-api/status', {headers:{'X-MiroFish-Studio':'1'}}); const body = await r.json(); status.value = body.data }
  catch { error.value = '无法连接本地工作台，请重新打开桌面入口。' }
  if (!closed) statusTimer = window.setTimeout(refreshStatus, 5000)
}
onMounted(refreshStatus)
onBeforeUnmount(() => { closed = true; window.clearTimeout(statusTimer) })
const submit = () => {
  if (!canSubmit.value || submitting.value || !engineReady.value) return
  const upload = [...files.value]
  if (seed.value.trim()) upload.push(new File([seed.value], '背景材料.txt', {type:'text/plain'}))
  if (upload.reduce((sum,f) => sum+f.size, 0) > maxSize) { error.value = '全部材料超过 50 MB，请减少材料后重试。'; return }
  submitting.value = true
  setPendingUpload(upload, requirement.value.trim(), name.value || requirement.value.trim().slice(0,30))
  router.push({name:'Process',params:{projectId:'new'}})
}
</script>

<style scoped src="../assets/studio-creation.css"></style>
