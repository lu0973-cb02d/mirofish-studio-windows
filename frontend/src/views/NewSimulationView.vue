<template>
  <div class="new-workspace">
    <header><RouterLink to="/" class="brand">MiroFish <span>Studio</span></RouterLink><RouterLink to="/">← 返回工作台</RouterLink></header>
    <main>
      <div class="intro"><span class="eyebrow">NEW SIMULATION · 新建推演</span><h1>从一个值得探索的问题开始。</h1><p>提供背景材料，描述你想了解的变化。接下来将建立图谱、设定角色，再运行双线推演。</p></div>
      <div class="create-grid">
        <form @submit.prevent="submit">
          <section class="name-section"><label for="project-name">推演名称 <span class="optional">选填</span></label><input id="project-name" v-model.trim="name" maxlength="100" placeholder="起一个容易找到的名字；留空会取目标的前 30 字" /></section>
          <section><div class="section-heading"><span class="number">01</span><div><h2>放入背景材料</h2><p>直接粘贴文字，也可以上传文档，两种方式可同时使用。</p></div></div>
            <label for="seed">背景文字 <span class="optional">选填</span></label>
            <textarea id="seed" v-model="seed" rows="7" placeholder="描述真实的起点：参与者、当前情况、发生过的事情，以及你已经知道的信息。" maxlength="200000"></textarea>
            <div class="dropzone" :class="{ over: dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="drop">
              <svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4"/></svg>
              <div><strong>拖入文档，或 <button type="button" class="text-button" @click="input?.click()">选择文件</button></strong><p>PDF、TXT、Markdown · 合计不超过 50 MB</p></div>
              <input ref="input" type="file" accept=".pdf,.txt,.md,.markdown" multiple hidden @change="selectFiles" />
            </div>
            <ul class="files"><li v-for="(file, i) in files" :key="file.name + file.size"><span>{{ file.name }}</span><small>{{ formatSize(file.size) }}</small><button type="button" :aria-label="`移除 ${file.name}`" @click="files.splice(i,1)">×</button></li></ul>
          </section>
          <section><div class="section-heading"><span class="number">02</span><div><h2>说清楚推演目标</h2><p>聚焦一个核心问题，后续还可以设置轮数与角色。</p></div></div>
            <label for="requirement">你想推演什么？</label>
            <textarea id="requirement" v-model="requirement" rows="5" required maxlength="15000" placeholder="例如：如果这项产品调整正式上线，不同用户群体会如何反应？哪些条件下可能出现另一种结果？"></textarea>
            <div class="tip">把已知事实放在材料里，把假设写在目标里，能让结果更容易理解和比较。</div>
          </section>
          <div v-if="error" class="error" role="alert">{{ error }}</div>
          <div class="submit-row"><span>结果供探索与比较使用，不代表确定预测。</span><button type="submit" class="primary" :disabled="!canSubmit || submitting || !engineReady">{{ submitting ? '正在进入…' : '开始构建推演 →' }}</button></div>
        </form>
        <aside>
          <div class="connection"><span class="eyebrow">本次使用</span><h3>{{ status?.active_model?.name || '尚未选择模型' }}</h3><p class="model-name">{{ status?.active_model?.model || '返回工作台配置连接' }}</p><div class="badge" :class="{ ready: engineReady }">{{ engineReady ? '引擎已就绪' : '引擎未就绪' }}</div><p v-if="!engineReady">请先回工作台确认连接与运行状态。已填写的文字会保留。</p><RouterLink to="/">管理连接与服务 ↗</RouterLink></div>
          <div class="journey"><h3>接下来会发生什么</h3><ol><li><strong>建立图谱</strong><span>从材料中提取角色与关系</span></li><li><strong>设定世界</strong><span>检查人设、平台与推演轮数</span></li><li><strong>运行推演</strong><span>观察两条线的行动和变化</span></li><li><strong>生成报告</strong><span>结合图谱与采访整理发现</span></li></ol><p>关闭标签页不会停止后台任务。完成后可以从工作台的记录继续查看。</p></div>
        </aside>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, toRef, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { setPendingUpload, newProjectDraft } from '../store/pendingUpload'

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

<style scoped>
.name-section{padding:20px 28px}.name-section input{width:100%;padding:12px 14px;font:14px 'Segoe UI','Microsoft YaHei',sans-serif;color:#263d32;border:1px solid #d7e1d8;border-radius:9px;background:#fcfdfb}
.new-workspace{background:#f6f7f5;min-height:100vh;color:#1d332c;font:15px/1.7 'Segoe UI','Microsoft YaHei',sans-serif}header{height:76px;border-bottom:1px solid #e0e6df;display:flex;align-items:center;justify-content:space-between;padding:0 5vw;background:#fff}.brand{font-size:21px;font-weight:750;letter-spacing:-.6px}.brand span{font-weight:400;color:#638074}a{color:#276a55;text-decoration:none}main{max-width:1240px;margin:auto;padding:46px 32px 70px}.eyebrow{font-size:11px;letter-spacing:1.8px;color:#628074;font-weight:700}h1{font-size:32px;letter-spacing:-.9px;line-height:1.4;margin:11px 0 12px}.intro>p{color:#66766e}.create-grid{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:28px;margin-top:32px}section,.connection,.journey{background:#fff;border:1px solid #dfe7e0;border-radius:16px;padding:28px;margin-bottom:20px}.section-heading{display:flex;gap:14px;margin-bottom:24px}.number{border-radius:10px;background:#edf5ef;color:#257556;width:39px;height:39px;display:grid;place-items:center;font-weight:700;flex-shrink:0}h2{font-size:18px;line-height:1.5}.section-heading p,.dropzone p{font-size:13px;color:#6c7b73;margin-top:4px}label{display:block;font-size:14px;font-weight:600;margin-bottom:9px}.optional{font-size:12px;color:#859087;font-weight:400;margin-left:8px}textarea{border:1px solid #d7e1d8;border-radius:10px;width:100%;padding:14px;font-family:inherit;font-size:14px;line-height:1.8;color:#263d32;resize:vertical;background:#fcfdfb}textarea::placeholder{color:#89948d;font:14px/1.8 'Segoe UI','Microsoft YaHei',sans-serif}.dropzone{display:flex;align-items:center;justify-content:center;gap:15px;border:1.5px dashed #cbdccf;background:#f8fbf8;border-radius:10px;padding:24px 12px;margin-top:15px;color:#39705a}.dropzone.over{background:#e5f2e8;border-color:#268266}button{cursor:pointer;font:inherit}button:disabled{cursor:not-allowed;opacity:.45}.text-button{border:none;background:none;color:#147d64;font-weight:700;text-decoration:underline}.files{list-style:none;margin-top:12px}.files li{display:flex;align-items:center;gap:12px;padding:10px;border-bottom:1px solid #eef2ed;min-width:0}.files li span{flex:1;overflow-wrap:anywhere;font-size:13px}.files small{color:#7c8b81}.files button{border:none;background:#f1f4ef;color:#6b7b6e;width:30px;height:30px;border-radius:6px}.tip{font-size:12px;margin-top:12px;color:#6a7d70}.submit-row{display:flex;align-items:center;justify-content:space-between;gap:16px;font-size:12px;color:#718277}.primary{border:none;background:#147d64;color:white;font-size:14px;font-weight:600;padding:14px 23px;border-radius:9px;white-space:nowrap}.primary:hover:not(:disabled){background:#0d634f}.error{background:#fff0ea;color:#a6422f;border:1px solid #f0c8b8;padding:14px;border-radius:9px;margin-bottom:16px}.connection h3{font-size:19px;margin-top:10px}.connection p{font-size:13px;margin:10px 0;color:#76867a}.model-name{overflow-wrap:anywhere}.badge{display:inline-block;border:1px solid #ddd8bc;background:#fffbed;color:#8c7336;border-radius:20px;padding:3px 10px;font-size:12px;margin-bottom:14px}.badge.ready{background:#edf7ef;border-color:#cde4d0;color:#28704e}.connection>a{display:block;font-size:13px;padding-top:14px;border-top:1px solid #edf0ea}.journey h3{font-size:15px;margin-bottom:24px}.journey ol{list-style:none;counter-reset:step}.journey li{position:relative;padding:0 0 23px 32px;border-left:1px solid #dbe7dd;margin-left:12px;counter-increment:step}.journey li:last-child{border:none}.journey li:before{content:counter(step);position:absolute;left:-12px;top:0;border-radius:50%;width:23px;height:23px;background:#eaf2eb;color:#558063;display:grid;place-items:center;font-size:11px}.journey li strong{display:block;font-size:13px}.journey li span{font-size:12px;color:#77857b}.journey>p{font-size:12px;color:#829082;line-height:1.8;border-top:1px solid #edf0ea;padding-top:17px}:focus-visible{outline:3px solid #9dcfb6;outline-offset:3px}@media(max-width:900px){.create-grid{grid-template-columns:1fr}aside{display:grid;grid-template-columns:1fr 1fr;gap:16px}.submit-row{flex-wrap:wrap}}@media(max-width:600px){header{height:65px;padding:0 20px}main{padding:28px 16px}h1{font-size:26px}section,.connection,.journey{padding:20px}aside{display:block}.dropzone{padding:18px 10px}.submit-row .primary{width:100%}}
</style>
