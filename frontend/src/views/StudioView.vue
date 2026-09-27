<template>
  <div class="studio-shell">
    <a class="skip-link" href="#studio-main">跳到工作台内容</a>
    <aside class="studio-sidebar" aria-label="工作台导航">
      <router-link class="studio-brand" to="/" aria-label="MiroFish Studio 工作台">
        <span class="brand-symbol"><Icon name="spark" /></span>
        <span class="brand-type">MiroFish<span>STUDIO <i>1.0</i></span></span>
      </router-link>
      <div class="sidebar-label">你的推演空间</div>
      <nav class="studio-nav">
        <button v-for="item in navigation" :key="item.id" type="button" :class="{ active: tab === item.id }" :aria-label="item.name" :title="item.name" :aria-current="tab === item.id ? 'page' : undefined" @click="setTab(item.id)">
          <Icon :name="item.icon" /><span>{{ item.name }}</span><Icon v-if="tab === item.id" class="nav-arrow" name="chevron" />
        </button>
      </nav>
      <div class="sidebar-bottom">
        <button class="quit-studio" :disabled="!!action || status.busy || !connected" @click="quitStudio"><Icon name="power" /><span>退出工作台</span></button>
        <div class="sidebar-note"><Icon name="shield" /><span>配置保存在本机<br><small>让探索保持简单</small></span></div>
        <div class="studio-connection"><span class="status-dot" :class="{ good: connected, muted: !connected }"></span>{{ connected ? '本地工作台已连接' : initialLoading ? '正在连接工作台' : '工作台连接中断' }}</div>
      </div>
    </aside>

    <main id="studio-main" class="studio-main" tabindex="-1">
      <header class="topbar">
        <div class="breadcrumb">本地工作台 <span>/</span> <strong>{{ currentNavigation.name }}</strong></div>
        <div class="topbar-actions"><span class="version-pill">Studio v{{ status.version || '1.1.0' }}</span><button class="icon-button" type="button" aria-label="刷新工作台状态" title="刷新状态" :disabled="refreshing" @click="refreshAll"><Icon name="refresh" :class="{ spinning: refreshing }" /></button></div>
      </header>

      <div class="workspace">
        <div v-if="closedByUser" class="alert alert-success" role="status"><Icon name="check" /><p>工作台已退出，配置与记录已保留。再次使用时双击桌面上的「MiroFish 工作台」。</p></div>
        <div v-else-if="!connected && !initialLoading" class="alert alert-error connection-alert" role="alert"><Icon name="info" /><div><strong>暂时无法连接本地工作台</strong><p>{{ connectionError }}</p></div><button class="button button-small button-soft" :disabled="refreshing" @click="refreshAll">重新连接</button></div>
        <div v-if="notice" class="alert notice" :class="notice.type === 'error' ? 'alert-error' : 'alert-success'" :role="notice.type === 'error' ? 'alert' : 'status'"><Icon :name="notice.type === 'error' ? 'info' : 'check'" /><p>{{ notice.message }}</p><button class="icon-button" type="button" aria-label="关闭提示" @click="notice = null"><Icon name="close" /></button></div>

        <template v-if="tab === 'dashboard'">
          <section class="page-heading">
            <div><p class="eyebrow">WELCOME TO YOUR WORKSPACE</p><h1>让每一次推演，从容开始。</h1><p class="page-description">选好模型，连接记忆，把下一种可能交给推演。</p></div>
            <button class="button button-primary" :disabled="initialLoading || !!action || !connected" @click="primaryAction"><Icon :name="primaryActionIcon" />{{ primaryActionLabel }}<Icon name="arrow" /></button>
          </section>

          <div class="dashboard-top">
            <section class="launch-card">
              <div class="launch-copy"><span class="section-kicker"><span class="tiny-square"></span> 开始之前</span><h2>{{ canCreate ? '准备就绪，开始探索。' : '一次配置，随时出发。' }}</h2><p>从模型到记忆连接，只需几步。<br>你的预设会保留，下次直接使用。</p></div>
              <div class="setup-steps">
                <button class="setup-step" :class="{ complete: modelReady }" @click="setTab('models')"><span class="step-number"><Icon v-if="modelReady" name="check" /><template v-else>01</template></span><span><strong>选择 AI 模型</strong><small>{{ modelReady ? activeModel.name : '保存地址、密钥与模型' }}</small></span><Icon name="chevron" /></button>
                <button class="setup-step" :class="{ complete: zepReady }" @click="setTab('zep')"><span class="step-number"><Icon v-if="zepReady" name="check" /><template v-else>02</template></span><span><strong>连接 Zep 记忆</strong><small>{{ zepReady ? status.zep?.active_name || activeZep.name : '配置连接和备用密钥' }}</small></span><Icon name="chevron" /></button>
                <button class="setup-step" :class="{ complete: engineReady }" :disabled="!!action || !connected" @click="engineReady ? openNew() : engineAction('start')"><span class="step-number"><Icon v-if="engineReady" name="check" /><template v-else>03</template></span><span><strong>{{ engineReady ? '创建新的推演' : '启动推演引擎' }}</strong><small>{{ engineReady ? canCreate ? '从一份材料、一个问题开始' : '完成上面的配置后即可开始' : '启动后即可进入推演流程' }}</small></span><Icon :name="action === 'engine-start' ? 'loader' : 'arrow'" :class="{ spinning: action === 'engine-start' }" /></button>
              </div>
              <div class="launch-orbit" aria-hidden="true"><div></div><div></div><span><Icon name="spark" /></span></div>
            </section>

            <section class="surface engine-card" aria-labelledby="engine-title">
              <div class="section-title"><h2 id="engine-title">推演引擎</h2><span class="badge" :class="engineBadgeClass"><span class="status-dot" :class="engineReady ? 'good' : 'muted'"></span>{{ engineLabel }}</span></div>
              <div class="engine-visual" :class="{ ready: engineReady }"><Icon name="power" /><span>{{ engineReady ? '引擎已就绪' : status.engine?.state === 'starting' ? '正在准备环境' : status.engine?.state === 'error' ? '需要检查连接' : '等待启动' }}</span></div>
              <p class="engine-message">{{ status.engine?.message || (initialLoading ? '正在读取运行状态…' : '启动本地引擎，开始创建与查看推演。') }}</p>
              <div v-if="status.busy" class="inline-info"><Icon name="activity" /><span>有任务正在进行，完成后可切换或重启。</span></div>
              <div v-else-if="status.engine?.interview_count" class="inline-info"><Icon name="info" /><span>{{ status.engine.interview_count }} 个已完成推演仍可采访。停止或重启引擎会关闭采访环境。</span></div>
              <div class="engine-controls">
                <button v-if="!engineReady && status.engine?.state !== 'starting'" class="button button-primary" :disabled="!!action || !connected" @click="engineAction('start')"><Icon :name="action === 'engine-start' ? 'loader' : 'play'" :class="{ spinning: action === 'engine-start' }" />{{ action === 'engine-start' ? '正在启动…' : '启动引擎' }}</button>
                <template v-else><button class="button button-soft" :disabled="!!action || status.busy || status.engine?.state === 'starting' || !connected" @click="engineAction('restart')"><Icon :name="action === 'engine-restart' ? 'loader' : 'refresh'" :class="{ spinning: action === 'engine-restart' }" />{{ action === 'engine-restart' ? '重启中…' : '重启' }}</button><button class="button button-outline" :disabled="!!action || status.busy || status.engine?.state === 'starting' || !connected" @click="engineAction('stop')"><Icon :name="action === 'engine-stop' ? 'loader' : 'stop'" :class="{ spinning: action === 'engine-stop' }" />{{ action === 'engine-stop' ? '停止中…' : '停止' }}</button></template>
              </div>
              <div class="engine-foot"><span>每 5 秒自动更新</span><span v-if="engineReady && status.uptime_seconds != null">已运行 {{ formatUptime(status.uptime_seconds) }}</span><span v-else>仅在本机运行</span></div>
            </section>
          </div>

          <section class="stat-grid" aria-label="本机记录概览">
            <div v-for="metric in metrics" :key="metric.name" class="surface stat-card"><span class="stat-icon"><Icon :name="metric.icon" /></span><div><span class="stat-label">{{ metric.name }}</span><strong>{{ initialLoading || !hasStatus ? '—' : metric.value }}</strong></div><span class="stat-caption">本机保存</span></div>
          </section>

          <div class="dashboard-bottom">
            <section class="surface recent-card"><div class="section-title"><h2>最近的推演</h2><button class="text-button" @click="setTab('records')">全部记录<Icon name="arrow" /></button></div><div v-if="recordsLoading" class="empty-state compact"><Icon class="spinning" name="loader" /><p>正在读取记录…</p></div><div v-else-if="recordsError" class="empty-state compact"><Icon name="info" /><p>{{ recordsError }}</p><button class="text-button" @click="loadRecords">重试</button></div><div v-else-if="!recentProjects.length" class="empty-state compact"><span class="empty-icon"><Icon name="folder" /></span><h3>第一段探索，等你开启</h3><p>创建推演后，最近的项目会出现在这里。</p><button class="text-button" :disabled="!canCreate" @click="openNew">创建第一条推演<Icon name="arrow" /></button></div><div v-else class="recent-list"><button v-for="project in recentProjects" :key="project.project_id" class="recent-row" :disabled="!engineReady" @click="openRecord(project)"><span class="record-icon"><Icon :name="project.report_id ? 'file' : 'folder'" /></span><span class="recent-main"><strong>{{ project.name || '未命名推演' }}</strong><small>{{ formatDate(project.created_at) }}</small></span><span class="badge badge-neutral">{{ recordStatus(project.report_status || project.simulation_status || project.status) }}</span><Icon name="chevron" /></button></div><p v-if="recentProjects.length && !engineReady" class="card-bottom-note">启动引擎后，即可打开已有项目。</p></section>
            <section class="surface current-card"><div class="section-title"><h2>当前配置</h2><span class="quiet-label">新任务使用</span></div><button class="current-config" @click="setTab('models')"><span class="config-icon"><Icon name="cpu" /></span><span><small>AI 模型</small><strong>{{ activeModel?.name || '尚未选择模型预设' }}</strong><em>{{ activeModel?.model || '添加并设为当前，即可使用' }}</em></span><Icon name="chevron" /></button><button class="current-config" @click="setTab('zep')"><span class="config-icon"><Icon name="link" /></span><span><small>Zep 记忆连接</small><strong>{{ status.zep?.active_name || activeZep?.name || '尚未配置 Zep' }}</strong><em>{{ config.auto_zep ? '自动切换已开启' : '自动切换已关闭' }} · {{ config.zep.length }} 个已存连接</em></span><Icon name="chevron" /></button><div class="local-note"><Icon name="shield" /><p>密钥由本机加密保存；调用时发送给你配置的服务。</p></div></section>
          </div>
          <details class="logs-panel" @toggle="onLogsToggle"><summary><span><Icon name="activity" />运行日志</span><span>遇到问题时查看<Icon name="chevron" /></span></summary><div class="logs-toolbar"><span>最近的运行信息</span><button class="text-button" :disabled="logsLoading" @click="loadLogs"><Icon name="refresh" :class="{ spinning: logsLoading }" />刷新</button></div><pre class="log-output">{{ logsLoading && !logs.length ? '正在读取日志…' : logsError || logs.join('\n') || '暂无运行日志。' }}</pre></details>
        </template>

        <template v-else-if="tab === 'models'">
          <section class="page-heading"><div><p class="eyebrow">MODEL LIBRARY</p><h1>好模型，随手切换。</h1><p class="page-description">保存多套服务地址、密钥与模型，让每种任务都有合适的选择。</p></div><button class="button button-primary" :disabled="!!action" @click="newModel"><Icon name="plus" />添加模型预设</button></section>
          <div v-if="status.busy" class="alert alert-info"><Icon name="info" /><p>当前有任务进行中。你可以保存新预设，任务结束后再切换正在使用的配置。</p></div>
          <div class="config-layout">
            <section class="config-list-section" aria-labelledby="models-title"><div class="list-heading"><h2 id="models-title">我的模型预设 <span>{{ config.models.length }}</span></h2><span class="quiet-label">保存后随时使用</span></div>
              <div v-if="initialLoading" class="surface empty-state"><Icon class="spinning" name="loader" /><p>正在读取预设…</p></div>
              <div v-else-if="!config.models.length" class="surface empty-state tall-empty"><span class="empty-icon"><Icon name="cpu" /></span><h3>为第一个模型安个家</h3><p>填入服务地址与 API Key，获取模型列表，<br>保存为你的第一套预设。</p><div class="empty-tip"><Icon name="arrow" />从右侧表单开始</div></div>
              <article v-for="model in config.models" :key="model.id" class="surface preset-card" :class="{ selected: model.id === config.active_model_id, editing: model.id === modelForm.id }"><div class="preset-top"><span class="preset-icon"><Icon name="cpu" /></span><div class="preset-title"><h3>{{ model.name }}</h3><span>{{ endpointLabel(model.base_url) }}</span></div><span v-if="model.id === config.active_model_id" class="badge badge-green"><Icon name="check" />当前使用</span></div><div class="model-name">{{ model.model || '尚未设置模型' }}</div><div class="preset-details"><span><span class="status-dot" :class="model.has_key ? 'good' : 'muted'"></span>{{ model.has_key ? `密钥已保存${model.key_hint ? ' · ' + model.key_hint : ''}` : '尚未保存密钥' }}</span><span v-if="model.enabled === false">已停用</span></div><div class="preset-actions"><button class="button button-small" :class="model.id === config.active_model_id ? 'button-soft' : 'button-primary'" :disabled="!!action || model.id === config.active_model_id || !modelHasCredentials(model) || !model.model || model.enabled === false || status.busy" @click="activateModel(model)"><Icon v-if="action === `activate-model-${model.id}`" class="spinning" name="loader" /><Icon v-else :name="model.id === config.active_model_id ? 'check' : 'play'" />{{ model.id === config.active_model_id ? '正在使用' : action === `activate-model-${model.id}` ? '切换中…' : '设为当前' }}</button><div><button class="icon-button" :disabled="!!action" :aria-label="`编辑 ${model.name}`" title="编辑预设" @click="editModel(model)"><Icon name="edit" /></button><button class="icon-button danger-icon" :disabled="!!action || status.busy" :aria-label="`删除 ${model.name}`" title="删除预设" @click="deleteModel(model)"><Icon name="trash" /></button></div></div></article>
              <p class="section-footnote"><Icon name="info" />启用后用于新任务。已有采访环境保留原配置；任务进行中请在完成后切换。</p>
            </section>

            <section class="surface editor-panel" aria-labelledby="model-editor-title"><div class="editor-title"><div><span class="section-kicker">{{ modelForm.id ? 'EDIT PRESET' : 'NEW PRESET' }}</span><h2 id="model-editor-title">{{ modelForm.id ? '编辑模型预设' : '添加模型预设' }}</h2></div><button v-if="modelForm.id" class="text-button" :disabled="!!action" @click="newModel">新建</button></div>
              <form @submit.prevent="saveModel"><fieldset :disabled="!!action"><div v-if="config.presets.length" class="form-field"><label for="model-provider">快速填入服务地址 <span class="optional">可选</span></label><select id="model-provider" v-model="quickPreset" @change="applyQuickPreset"><option value="">自定义 / 选择服务商</option><option v-for="(preset, index) in config.presets" :key="preset.name" :value="String(index)">{{ preset.name }}</option></select></div>
                <div class="form-field"><label for="model-name">预设名称</label><input id="model-name" ref="modelNameInput" v-model.trim="modelForm.name" required maxlength="80" placeholder="例如：日常推演 · 快速模型" autocomplete="off" /></div>
                <div class="form-field"><label for="model-base-url">服务地址 <span class="field-en">Base URL</span></label><input id="model-base-url" v-model.trim="modelForm.base_url" type="url" required placeholder="https://api.example.com/v1" spellcheck="false" autocomplete="off" aria-describedby="base-url-help" /><p id="base-url-help" class="field-help">填写兼容 OpenAI 的完整接口基础地址。</p></div>
                <div class="form-field"><label for="model-key">API Key <span v-if="editingModel?.has_key" class="saved-label">已保存</span></label><div class="input-with-button"><input id="model-key" v-model.trim="modelForm.key" :type="showModelKey ? 'text' : 'password'" :required="!editingModel?.has_key && !isLocalEndpoint(modelForm.base_url)" :placeholder="editingModel?.has_key ? '留空保留已保存的密钥' : '粘贴你的 API Key'" autocomplete="off" spellcheck="false" /><button class="icon-button" type="button" :aria-label="showModelKey ? '隐藏模型密钥' : '显示模型密钥'" :aria-pressed="showModelKey" @click="showModelKey = !showModelKey"><Icon :name="showModelKey ? 'eye-off' : 'eye'" /></button></div></div>
                <div class="form-field"><div class="field-label-row"><label for="model-id">模型名称</label><button class="text-button" type="button" :disabled="!modelForm.base_url || (!modelForm.key && !editingModel?.has_key && !isLocalEndpoint(modelForm.base_url))" @click="discoverModels"><Icon :name="action === 'discover-models' ? 'loader' : 'refresh'" :class="{ spinning: action === 'discover-models' }" />{{ action === 'discover-models' ? '正在获取…' : '获取模型' }}</button></div><input id="model-id" v-model.trim="modelForm.model" list="studio-model-options" required placeholder="获取后选择，或手动输入模型名称" autocomplete="off" spellcheck="false" /><datalist id="studio-model-options"><option v-for="name in discoveredModels" :key="name" :value="name" /></datalist><p class="field-help">{{ discoveredModels.length ? `已获取 ${discoveredModels.length} 个模型，点击输入框选择，也可输入关键字。` : '有些服务不提供模型列表，可以直接填写准确名称。' }}</p></div>
              </fieldset><div v-if="modelFeedback" class="form-feedback" :class="modelFeedback.type" :role="modelFeedback.type === 'error' ? 'alert' : 'status'"><Icon :name="modelFeedback.type === 'error' ? 'info' : 'check'" /><span>{{ modelFeedback.message }}</span></div><div class="form-actions"><button class="button button-outline" type="button" :disabled="!!action || !connected" @click="testModel"><Icon :name="action === 'test-model' ? 'loader' : 'activity'" :class="{ spinning: action === 'test-model' }" />{{ action === 'test-model' ? '测试中…' : '测试连接' }}</button><button class="button button-primary" type="submit" :disabled="!!action || !connected"><Icon :name="action === 'save-model' ? 'loader' : 'check'" :class="{ spinning: action === 'save-model' }" />{{ action === 'save-model' ? '保存中…' : '保存预设' }}</button></div><p class="form-footer">{{ modelForm.id && modelForm.id === config.active_model_id ? '当前预设保存后，将直接用于新任务。' : '保存后，在预设卡片点击「设为当前」即可切换。' }}</p></form>
            </section>
          </div>
        </template>

        <template v-else-if="tab === 'zep'">
          <section class="page-heading"><div><p class="eyebrow">MEMORY CONNECTIONS</p><h1>让记忆连接，保持顺畅。</h1><p class="page-description">统一保存 Zep 密钥，为同一项目配置备用连接。</p></div><button class="button button-primary" :disabled="!!action" @click="newZep"><Icon name="plus" />添加 Zep 连接</button></section>
          <section class="surface rotation-card"><div class="rotation-icon"><Icon name="refresh" /></div><div class="rotation-copy"><div><h2>自动切换可用密钥</h2><span class="badge" :class="config.auto_zep ? 'badge-green' : 'badge-neutral'">{{ config.auto_zep ? '已开启' : '已关闭' }}</span></div><p>当前连接不可用时，尝试同组的其他可用密钥，减少手动处理。</p></div><button class="switch" role="switch" :aria-checked="config.auto_zep" aria-label="自动切换 Zep 可用密钥" :class="{ on: config.auto_zep }" :disabled="!!action || !connected" @click="toggleRotation"><span></span></button></section>
          <div class="config-layout"><section class="config-list-section" aria-labelledby="zep-list-title"><div class="list-heading"><h2 id="zep-list-title">我的 Zep 连接 <span>{{ config.zep.length }}</span></h2><span class="quiet-label">{{ status.zep?.available ?? config.zep.filter(item => item.enabled !== false && item.has_key).length }} 个已启用</span></div><div v-if="initialLoading" class="surface empty-state"><Icon class="spinning" name="loader" /><p>正在读取连接…</p></div><div v-else-if="!config.zep.length" class="surface empty-state tall-empty"><span class="empty-icon"><Icon name="link" /></span><h3>为推演连接长期记忆</h3><p>保存第一条 Zep 连接，再添加同一项目的<br>备用密钥，组成可自动切换的连接组。</p><div class="empty-tip"><Icon name="arrow" />从右侧表单开始</div></div>
              <article v-for="connection in config.zep" :key="connection.id" class="surface preset-card zep-card" :class="{ selected: connection.id === config.active_zep_id, editing: connection.id === zepForm.id }"><div class="preset-top"><span class="preset-icon"><Icon name="link" /></span><div class="preset-title"><h3>{{ connection.name }}</h3><span>连接组 · {{ connection.group || '独立连接' }}</span></div><span v-if="connection.id === config.active_zep_id" class="badge badge-green"><Icon name="check" />当前使用</span><span v-else-if="connection.enabled === false" class="badge badge-neutral">已停用</span><span v-else class="badge badge-neutral">备用连接</span></div><div class="key-summary"><Icon name="shield" /><span>{{ connection.has_key ? connection.key_hint || '密钥已安全保存' : '尚未保存密钥' }}</span></div><div class="preset-actions"><button class="button button-small" :class="connection.id === config.active_zep_id ? 'button-soft' : 'button-primary'" :disabled="!!action || connection.id === config.active_zep_id || !connection.has_key || connection.enabled === false || status.busy" @click="activateZep(connection)"><Icon :name="action === `activate-zep-${connection.id}` ? 'loader' : connection.id === config.active_zep_id ? 'check' : 'play'" :class="{ spinning: action === `activate-zep-${connection.id}` }" />{{ connection.id === config.active_zep_id ? '正在使用' : action === `activate-zep-${connection.id}` ? '切换中…' : '设为当前' }}</button><div><button class="icon-button" :disabled="!!action" :aria-label="`编辑 ${connection.name}`" title="编辑连接" @click="editZep(connection)"><Icon name="edit" /></button><button class="icon-button danger-icon" :disabled="!!action || status.busy" :aria-label="`删除 ${connection.name}`" title="删除连接" @click="deleteZep(connection)"><Icon name="trash" /></button></div></div></article>
              <div class="group-explainer"><Icon name="info" /><div><strong>同一个项目，放在同一个连接组</strong><p>备用密钥必须能访问相同的 Zep 项目和图谱。不同账号或项目的密钥，请使用不同组名；它们不能接替已有图谱的连接。</p></div></div>
            </section>
            <section class="surface editor-panel" aria-labelledby="zep-editor-title"><div class="editor-title"><div><span class="section-kicker">{{ zepForm.id ? 'EDIT CONNECTION' : 'NEW CONNECTION' }}</span><h2 id="zep-editor-title">{{ zepForm.id ? '编辑 Zep 连接' : '添加 Zep 连接' }}</h2></div><button v-if="zepForm.id" class="text-button" :disabled="!!action" @click="newZep">新建</button></div><form @submit.prevent="saveZep"><fieldset :disabled="!!action"><div class="form-field"><label for="zep-name">连接名称</label><input id="zep-name" ref="zepNameInput" v-model.trim="zepForm.name" required maxlength="80" placeholder="例如：主项目 · 备用连接" autocomplete="off" /></div><div class="form-field"><label for="zep-group">连接组</label><input id="zep-group" v-model.trim="zepForm.group" maxlength="80" list="studio-zep-groups" placeholder="例如：我的主项目" autocomplete="off" aria-describedby="zep-group-help" /><datalist id="studio-zep-groups"><option v-for="group in zepGroups" :key="group" :value="group" /></datalist><p id="zep-group-help" class="field-help">可留空作为独立账号。能访问同一图谱的密钥填写同一组名，才会在已有推演中互为备用。</p></div><div class="form-field"><label for="zep-key">Zep API Key <span v-if="editingZep?.has_key" class="saved-label">已保存</span></label><div class="input-with-button"><input id="zep-key" v-model.trim="zepForm.key" :type="showZepKey ? 'text' : 'password'" :required="!editingZep?.has_key" :placeholder="editingZep?.has_key ? '留空保留已保存的密钥' : '粘贴你的 Zep API Key'" autocomplete="off" spellcheck="false" /><button class="icon-button" type="button" :aria-label="showZepKey ? '隐藏 Zep 密钥' : '显示 Zep 密钥'" :aria-pressed="showZepKey" @click="showZepKey = !showZepKey"><Icon :name="showZepKey ? 'eye-off' : 'eye'" /></button></div></div><label class="checkbox-label"><input v-model="zepForm.enabled" type="checkbox" /><span>启用此连接<small>停用后不参与自动切换</small></span></label></fieldset><div v-if="zepFeedback" class="form-feedback" :class="zepFeedback.type" :role="zepFeedback.type === 'error' ? 'alert' : 'status'"><Icon :name="zepFeedback.type === 'error' ? 'info' : 'check'" /><span>{{ zepFeedback.message }}</span></div><div class="form-actions"><button class="button button-outline" type="button" :disabled="!!action || !connected" @click="testZep"><Icon :name="action === 'test-zep' ? 'loader' : 'activity'" :class="{ spinning: action === 'test-zep' }" />{{ action === 'test-zep' ? '测试中…' : '测试连接' }}</button><button class="button button-primary" type="submit" :disabled="!!action || !connected"><Icon :name="action === 'save-zep' ? 'loader' : 'check'" :class="{ spinning: action === 'save-zep' }" />{{ action === 'save-zep' ? '保存中…' : '保存连接' }}</button></div><p class="form-footer">连接信息保存在本机，已有密钥不会回显。</p></form></section>
          </div>
        </template>

        <template v-else-if="tab === 'records'">
          <section class="page-heading"><div><p class="eyebrow">YOUR EXPLORATION ARCHIVE</p><h1>留下探索，也留好退路。</h1><p class="page-description">查看本机推演，创建记录备份，在需要时恢复。</p></div><button class="button button-primary" :disabled="!!action || !connected" @click="createBackup"><Icon :name="action === 'create-backup' ? 'loader' : 'archive'" :class="{ spinning: action === 'create-backup' }" />{{ action === 'create-backup' ? '正在备份…' : '立即备份记录' }}</button></section>
          <section class="surface records-panel"><div class="section-title"><h2>推演记录 <span class="count-label">{{ records.projects.length }}</span></h2><div class="search-field"><Icon name="search" /><input v-model="recordQuery" type="search" aria-label="搜索推演记录" placeholder="搜索推演名称" /></div></div><div v-if="recordsLoading && !records.projects.length" class="empty-state"><Icon class="spinning" name="loader" /><p>正在读取推演记录…</p></div><div v-else-if="recordsError" class="empty-state"><Icon name="info" /><p>{{ recordsError }}</p><button class="button button-soft" @click="loadRecords">重新读取</button></div><div v-else-if="!filteredProjects.length" class="empty-state"><span class="empty-icon"><Icon :name="recordQuery ? 'search' : 'folder'" /></span><h3>{{ recordQuery ? '没有匹配的推演' : '这里还没有推演记录' }}</h3><p>{{ recordQuery ? '换一个关键词试试。' : '新建推演后，项目与报告会在这里集中管理。' }}</p></div><div v-else class="table-scroll"><table class="records-table"><thead><tr><th scope="col">项目</th><th scope="col">创建时间</th><th scope="col">进度</th><th scope="col"><span class="sr-only">操作</span></th></tr></thead><tbody><tr v-for="project in filteredProjects" :key="project.project_id"><td><div class="table-project"><span class="record-icon"><Icon :name="project.report_id ? 'file' : 'folder'" /></span><div><strong>{{ project.name || '未命名推演' }}</strong><small>{{ project.report_id ? '已关联报告' : project.simulation_id ? '已关联推演' : '项目材料' }}</small></div></div></td><td>{{ formatDate(project.created_at) }}</td><td><span class="badge badge-neutral">{{ recordStatus(project.report_status || project.simulation_status || project.status) }}</span></td><td><button class="text-button" :disabled="!engineReady" @click="openRecord(project)">{{ project.report_id ? '查看报告' : '继续查看' }}<Icon name="arrow" /></button></td></tr></tbody></table></div><p v-if="records.projects.length && !engineReady" class="card-bottom-note">请先在工作台启动引擎，再打开已有项目。</p></section>
          <section class="surface backups-panel"><div class="section-title"><div><h2>记录备份 <span class="count-label">{{ backups.length }}</span></h2><p class="section-subtitle">备份包含推演记录，不包含 API Key。</p></div><button class="text-button" :disabled="backupsLoading" @click="loadBackups"><Icon name="refresh" :class="{ spinning: backupsLoading }" />刷新</button></div><div v-if="backupsLoading && !backups.length" class="empty-state compact"><Icon class="spinning" name="loader" /><p>正在读取备份…</p></div><div v-else-if="backupsError" class="empty-state compact"><Icon name="info" /><p>{{ backupsError }}</p><button class="text-button" @click="loadBackups">重试</button></div><div v-else-if="!backups.length" class="empty-state compact"><span class="empty-icon"><Icon name="archive" /></span><h3>给重要探索，留一份副本</h3><p>点击「立即备份记录」，在本机保存当前记录。</p></div><div v-else class="backup-list"><div v-for="backup in backups" :key="backup.name" class="backup-row"><span class="backup-file-icon"><Icon name="archive" /></span><div class="backup-details"><strong :title="backup.name">{{ backup.name }}</strong><small>{{ formatDate(backup.created_at) }} <span>·</span> {{ formatSize(backup.size) }}<template v-if="backup.file_count != null"> <span>·</span> {{ backup.file_count }} 个文件</template></small></div><button class="button button-small button-outline" :disabled="!!action || !connected || status.engine?.state !== 'stopped'" :title="status.engine?.state !== 'stopped' ? '停止引擎后可以恢复记录' : '恢复此备份'" @click="restoreBackup(backup)"><Icon :name="action === `restore-${backup.name}` ? 'loader' : 'refresh'" :class="{ spinning: action === `restore-${backup.name}` }" />{{ action === `restore-${backup.name}` ? '恢复中…' : '恢复' }}</button></div></div><div class="backup-guidance"><Icon name="info" /><div><p>恢复需要先停止推演引擎；恢复前会为当前数据创建回退备份。</p><p>有记录变化时每 15 分钟自动备份，保留最近 20 份自动备份。页面断线可继续查看；程序中断不会自动从中间轮次续跑。</p><p v-if="status.paths?.backups" class="path-note">备份位置 <code>{{ status.paths.backups }}</code></p></div></div></section>
        </template>

        <footer class="workspace-footer"><span>MiroFish Studio</span><span>让复杂推演，始于简单。</span><span class="footer-local"><span class="status-dot" :class="connected ? 'good' : 'muted'"></span> 本地工作空间</span></footer>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { studioApi } from '../api/studio'
import Icon from '../components/studio/StudioIcon.vue'

const route = useRoute()
const router = useRouter()
const navigation = [
  { id: 'dashboard', name: '工作台', icon: 'grid' },
  { id: 'models', name: '模型预设', icon: 'cpu' },
  { id: 'zep', name: 'Zep 连接', icon: 'link' },
  { id: 'records', name: '记录与备份', icon: 'archive' }
]
const validTab = value => navigation.some(item => item.id === value) ? value : 'dashboard'
const tab = ref(validTab(route.query.tab))
const currentNavigation = computed(() => navigation.find(item => item.id === tab.value))
const config = reactive({ version: '', active_model_id: null, active_zep_id: null, auto_zep: false, models: [], zep: [], presets: [] })
const status = reactive({ version: '', engine: { state: 'stopped', healthy: false }, counts: {}, zep: {}, paths: {}, busy: false })
const records = reactive({ projects: [], simulations: [], reports: [] })
const backups = ref([])
const logs = ref([])
const connected = ref(false)
const closedByUser = ref(false)
const hasStatus = ref(false)
const initialLoading = ref(true)
const refreshing = ref(false)
const recordsLoading = ref(false)
const backupsLoading = ref(false)
const logsLoading = ref(false)
const connectionError = ref('请确认本地工作台程序正在运行，页面会自动尝试重新连接。')
const recordsError = ref('')
const backupsError = ref('')
const logsError = ref('')
const notice = ref(null)
const action = ref('')
const recordQuery = ref('')
const modelNameInput = ref(null)
const zepNameInput = ref(null)
const modelForm = reactive({ id: '', name: '', base_url: '', model: '', key: '' })
const zepForm = reactive({ id: '', name: '', group: '', key: '', enabled: true })
const quickPreset = ref('')
const showModelKey = ref(false)
const showZepKey = ref(false)
const discoveredModels = ref([])
const modelFeedback = ref(null)
const zepFeedback = ref(null)
const lifetime = new AbortController()
let pollTimer
let noticeTimer
let disposed = false
let pollCount = 0
let coreGeneration = 0

const activeModel = computed(() => config.models.find(item => item.id === config.active_model_id))
const activeZep = computed(() => config.zep.find(item => item.id === config.active_zep_id))
const editingModel = computed(() => config.models.find(item => item.id === modelForm.id))
const editingZep = computed(() => config.zep.find(item => item.id === zepForm.id))
function isLocalEndpoint(address) {
  try { return ['localhost', '127.0.0.1', '[::1]'].includes(new URL(address).hostname) } catch { return false }
}
function modelHasCredentials(model) { return Boolean(model && (model.has_key || isLocalEndpoint(model.base_url))) }

const modelReady = computed(() => Boolean(modelHasCredentials(activeModel.value) && activeModel.value?.model && activeModel.value?.base_url && activeModel.value?.enabled !== false))
const zepReady = computed(() => Boolean(activeZep.value?.has_key && activeZep.value?.enabled !== false))
const engineReady = computed(() => status.engine?.state === 'running' && status.engine?.healthy)
const configurationReady = computed(() => status.engine?.configuration_synced !== false)
const canCreate = computed(() => connected.value && engineReady.value && configurationReady.value && modelReady.value && zepReady.value)
const engineLabel = computed(() => initialLoading.value ? '读取中' : !connected.value ? '状态未知' : ({ running: status.engine?.healthy ? '运行中' : '检查中', stopped: '已停止', starting: '启动中', error: '启动异常' }[status.engine?.state] || '状态未知'))
const engineBadgeClass = computed(() => engineReady.value ? 'badge-green' : status.engine?.state === 'error' ? 'badge-red' : 'badge-neutral')
const primaryActionLabel = computed(() => !modelReady.value ? '配置 AI 模型' : !zepReady.value ? '配置 Zep 连接' : !engineReady.value ? action.value === 'engine-start' ? '正在启动…' : '启动推演引擎' : !configurationReady.value ? '重启并确认配置' : '新建推演')
const primaryActionIcon = computed(() => !modelReady.value ? 'cpu' : !zepReady.value ? 'link' : !engineReady.value ? 'power' : 'plus')
const metrics = computed(() => [
  { name: '探索项目', icon: 'folder', value: status.counts?.projects ?? records.projects.length },
  { name: '推演记录', icon: 'activity', value: status.counts?.simulations ?? records.simulations.length },
  { name: '结果报告', icon: 'file', value: status.counts?.reports ?? records.reports.length }
])
const sortedProjects = computed(() => [...records.projects].sort((a, b) => (new Date(b.created_at).getTime() || 0) - (new Date(a.created_at).getTime() || 0)))
const recentProjects = computed(() => sortedProjects.value.slice(0, 4))
const filteredProjects = computed(() => sortedProjects.value.filter(item => !recordQuery.value || (item.name || '').toLocaleLowerCase().includes(recordQuery.value.toLocaleLowerCase())))
const zepGroups = computed(() => [...new Set(config.zep.map(item => item.group).filter(Boolean))])

function notify(message, type = 'success', persistent = false) {
  window.clearTimeout(noticeTimer)
  notice.value = { message, type }
  if (type !== 'error' && !persistent) noticeTimer = window.setTimeout(() => { notice.value = null }, 6000)
}

function setTab(value) {
  tab.value = validTab(value)
  router.replace({ path: route.path, query: tab.value === 'dashboard' ? {} : { tab: tab.value } })
}

watch(() => route.query.tab, value => { tab.value = validTab(value) })
watch(tab, value => {
  notice.value = null
  if (value === 'records') { loadRecords(); loadBackups() }
})
watch(() => [modelForm.id, modelForm.base_url, modelForm.key], () => { discoveredModels.value = []; modelFeedback.value = null })
watch(() => modelForm.model, () => { modelFeedback.value = null })
watch(() => [zepForm.id, zepForm.key], () => { zepFeedback.value = null })

async function refreshCore() {
  const generation = ++coreGeneration
  const results = await Promise.allSettled([studioApi.config(lifetime.signal), studioApi.status(lifetime.signal)])
  if (disposed || generation !== coreGeneration) return
  if (results[0].status === 'fulfilled') {
    const data = results[0].value || {}
    Object.assign(config, data, { models: Array.isArray(data.models) ? data.models : [], zep: Array.isArray(data.zep) ? data.zep : [], presets: Array.isArray(data.presets) ? data.presets : [] })
  }
  if (results[1].status === 'fulfilled') { Object.assign(status, results[1].value || {}); hasStatus.value = true }
  connected.value = results.every(item => item.status === 'fulfilled')
  if (!connected.value) connectionError.value = results.find(item => item.status === 'rejected')?.reason?.message || '暂时无法读取本地服务状态。'
}

async function loadRecords() {
  if (recordsLoading.value || disposed) return
  recordsLoading.value = true
  try {
    const data = await studioApi.records(lifetime.signal)
    Object.assign(records, { projects: data?.projects || [], simulations: data?.simulations || [], reports: data?.reports || [] })
    recordsError.value = ''
  } catch (error) { if (error.name !== 'AbortError') recordsError.value = error.message }
  finally { recordsLoading.value = false }
}

async function loadBackups() {
  if (backupsLoading.value || disposed) return
  backupsLoading.value = true
  try {
    const data = await studioApi.backups(lifetime.signal)
    backups.value = (Array.isArray(data) ? data : data?.backups || []).slice().sort((a, b) => (new Date(b.created_at).getTime() || 0) - (new Date(a.created_at).getTime() || 0))
    backupsError.value = ''
  } catch (error) { if (error.name !== 'AbortError') backupsError.value = error.message }
  finally { backupsLoading.value = false }
}

async function loadLogs() {
  if (logsLoading.value || disposed) return
  logsLoading.value = true
  try { const data = await studioApi.logs(lifetime.signal); logs.value = data?.lines || []; logsError.value = '' }
  catch (error) { if (error.name !== 'AbortError') logsError.value = error.message }
  finally { logsLoading.value = false }
}

function onLogsToggle(event) { if (event.target.open) loadLogs() }

async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try { await Promise.allSettled([refreshCore(), loadRecords(), loadBackups()]) }
  finally { refreshing.value = false; initialLoading.value = false }
}

async function poll() {
  if (disposed || closedByUser.value) return
  if (!refreshing.value && !action.value) {
    await refreshCore()
    pollCount += 1
    if (pollCount % 3 === 0 && (tab.value === 'dashboard' || tab.value === 'records')) await loadRecords()
  }
  if (!disposed) pollTimer = window.setTimeout(poll, 5000)
}

async function runAction(name, task, message) {
  if (action.value) return
  action.value = name
  try {
    const result = await task()
    if (message && !disposed) notify(result?.message || message, 'success', Boolean(result?.persistent_notice))
    return result
  } catch (error) {
    if (error.name !== 'AbortError' && !disposed) {
      if (['discover-models', 'test-model', 'save-model'].includes(name)) modelFeedback.value = { type: 'error', message: error.message }
      else if (['test-zep', 'save-zep'].includes(name)) zepFeedback.value = { type: 'error', message: error.message }
      else notify(error.message, 'error')
    }
    return undefined
  } finally { action.value = '' }
}

function primaryAction() {
  if (!connected.value) { notify('请先恢复与本地工作台的连接。', 'error'); return }
  if (!modelReady.value) setTab('models')
  else if (!zepReady.value) setTab('zep')
  else if (!engineReady.value) engineAction('start')
  else if (!configurationReady.value) engineAction('restart')
  else openNew()
}

function openNew() {
  if (!canCreate.value) return primaryAction()
  router.push('/new')
}

async function engineAction(command) {
  if (command !== 'start' && status.engine?.interview_count && !window.confirm('仍有已完成推演的采访环境。停止或重启会关闭这些环境，已保存的推演和采访记录会保留。确定继续？')) return
  await runAction(`engine-${command}`, async () => {
    const result = await studioApi.engine(command, lifetime.signal)
    await refreshCore()
    return result
  }, { start: '引擎启动请求已完成，运行状态已更新。', stop: '推演引擎已停止。', restart: '推演引擎已重启。' }[command])
}

async function quitStudio() {
  if (!window.confirm('退出会停止推演引擎并关闭采访环境，保留全部记录与配置。确定退出工作台？')) return
  await runAction('quit', async () => {
    await studioApi.quit(lifetime.signal)
    closedByUser.value = true
    connected.value = false
    window.clearTimeout(pollTimer)
    status.engine = { state: 'stopped', healthy: false }
  })
}

function focusEditor(input) { nextTick(() => { input.value?.focus({ preventScroll: true }); input.value?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'center' }) }) }

function newModel() {
  Object.assign(modelForm, { id: '', name: '', base_url: '', model: '', key: '' })
  quickPreset.value = ''; showModelKey.value = false; discoveredModels.value = []; modelFeedback.value = null
  focusEditor(modelNameInput)
}

function editModel(model) {
  Object.assign(modelForm, { id: model.id, name: model.name, base_url: model.base_url, model: model.model, key: '' })
  quickPreset.value = ''; showModelKey.value = false; modelFeedback.value = null
  focusEditor(modelNameInput)
}

function applyQuickPreset() {
  if (quickPreset.value === '') return
  const preset = config.presets[Number(quickPreset.value)]
  if (!preset) return
  modelForm.base_url = preset.base_url || ''
  modelForm.model = preset.model || ''
  if (!modelForm.name) modelForm.name = preset.name
}

function modelPayload() {
  return { ...(modelForm.id ? { id: modelForm.id } : {}), name: modelForm.name.trim(), base_url: modelForm.base_url.trim(), model: modelForm.model.trim(), ...(modelForm.key ? { key: modelForm.key.trim() } : {}) }
}

function validateModel(requireModel = true) {
  try {
    const url = new URL(modelForm.base_url)
    if (!['https:', 'http:'].includes(url.protocol)) throw new Error()
  } catch { modelFeedback.value = { type: 'error', message: '请填写完整的服务地址，以 https:// 或 http:// 开头。' }; return false }
  if (!modelForm.key && !editingModel.value?.has_key && !isLocalEndpoint(modelForm.base_url)) { modelFeedback.value = { type: 'error', message: '请先填写 API Key。' }; return false }
  if (requireModel && !modelForm.model.trim()) { modelFeedback.value = { type: 'error', message: '请先获取模型列表，或手动填写模型名称。' }; return false }
  return true
}

async function discoverModels() {
  if (!validateModel(false)) return
  await runAction('discover-models', async () => {
    const data = await studioApi.discoverModels(modelPayload(), lifetime.signal)
    discoveredModels.value = [...new Set((data?.models || []).filter(item => typeof item === 'string'))].sort()
    modelFeedback.value = { type: discoveredModels.value.length ? 'success' : 'info', message: data?.message || (discoveredModels.value.length ? `已获取 ${discoveredModels.value.length} 个模型，请在模型名称中选择。` : '服务没有返回模型列表，请手动填写模型名称。') }
    if (!modelForm.model && discoveredModels.value.length === 1) { modelForm.model = discoveredModels.value[0]; await nextTick(); modelFeedback.value = { type: 'success', message: '已获取并填入唯一可用的模型，你可以继续测试连接。' } }
  })
}

async function testModel() {
  if (!validateModel()) return
  await runAction('test-model', async () => {
    const data = await studioApi.testModel(modelPayload(), lifetime.signal)
    modelFeedback.value = { type: data?.ok === false ? 'error' : 'success', message: `${data?.message || (data?.ok === false ? '连接测试未通过。' : '连接正常，模型可以响应。')}${data?.latency_ms != null ? ` · ${formatLatency(data.latency_ms)}` : ''}` }
  })
}

async function saveModel() {
  if (!validateModel()) return
  if (!modelForm.name.trim()) { modelFeedback.value = { type: 'error', message: '请为这套预设起一个名称。' }; return }
  await runAction('save-model', async () => {
    const previousIds = new Set(config.models.map(item => item.id))
    const data = await studioApi.saveModel(modelPayload(), lifetime.signal)
    modelForm.key = ''; showModelKey.value = false
    await refreshCore()
    const saved = config.models.find(item => item.id === (modelForm.id || data?.id || data?.model?.id)) || config.models.find(item => !previousIds.has(item.id) && item.name === modelForm.name && item.base_url === modelForm.base_url && item.model === modelForm.model)
    if (saved) modelForm.id = saved.id
    await nextTick()
    modelFeedback.value = { type: 'success', message: saved?.id === config.active_model_id ? '当前预设已更新，新任务将使用更新后的配置。' : '预设已保存。点击对应卡片的「设为当前」即可使用。' }
    return data
  }, '模型预设已保存。')
}

async function activateModel(model) {
  await runAction(`activate-model-${model.id}`, async () => { const data = await studioApi.activateModel(model.id, lifetime.signal); await refreshCore(); return data }, `当前模型已切换为「${model.name}」。`)
}

async function deleteModel(model) {
  if (!window.confirm(`删除模型预设「${model.name}」？\n该预设保存的密钥也会删除，已有推演记录会保留。`)) return
  await runAction(`delete-model-${model.id}`, async () => { const data = await studioApi.removeModel(model.id, lifetime.signal); if (modelForm.id === model.id) newModel(); await refreshCore(); return data }, '模型预设已删除。')
}

function newZep() {
  Object.assign(zepForm, { id: '', name: '', group: '', key: '', enabled: true })
  showZepKey.value = false; zepFeedback.value = null; focusEditor(zepNameInput)
}

function editZep(connection) {
  Object.assign(zepForm, { id: connection.id, name: connection.name, group: connection.group || '', key: '', enabled: connection.enabled !== false })
  showZepKey.value = false; zepFeedback.value = null; focusEditor(zepNameInput)
}

function zepPayload() {
  return { ...(zepForm.id ? { id: zepForm.id } : {}), name: zepForm.name.trim(), group: zepForm.group.trim(), enabled: zepForm.enabled, ...(zepForm.key ? { key: zepForm.key.trim() } : {}) }
}

function validateZep() {
  if (!zepForm.key && !editingZep.value?.has_key) { zepFeedback.value = { type: 'error', message: '请先填写 Zep API Key。' }; return false }
  return true
}

async function testZep() {
  if (!validateZep()) return
  await runAction('test-zep', async () => {
    const data = await studioApi.testZep(zepPayload(), lifetime.signal)
    zepFeedback.value = { type: data?.ok === false ? 'error' : 'success', message: `${data?.message || (data?.ok === false ? '连接测试未通过。' : 'Zep 连接正常。')}${data?.latency_ms != null ? ` · ${formatLatency(data.latency_ms)}` : ''}` }
  })
}

async function saveZep() {
  if (!validateZep()) return
  if (!zepForm.name.trim()) { zepFeedback.value = { type: 'error', message: '请填写连接名称。' }; return }
  await runAction('save-zep', async () => {
    const previousIds = new Set(config.zep.map(item => item.id))
    const data = await studioApi.saveZep(zepPayload(), lifetime.signal)
    zepForm.key = ''; showZepKey.value = false
    await refreshCore()
    const saved = config.zep.find(item => item.id === (zepForm.id || data?.id || data?.connection?.id)) || config.zep.find(item => !previousIds.has(item.id) && item.name === zepForm.name && item.group === zepForm.group)
    if (saved) zepForm.id = saved.id
    await nextTick()
    zepFeedback.value = { type: 'success', message: 'Zep 连接已保存，可在连接卡片设为当前使用。' }
    return data
  }, 'Zep 连接已保存。')
}

async function activateZep(connection) {
  await runAction(`activate-zep-${connection.id}`, async () => { const data = await studioApi.activateZep(connection.id, lifetime.signal); await refreshCore(); return data }, `当前 Zep 连接已切换为「${connection.name}」。`)
}

async function deleteZep(connection) {
  if (!window.confirm(`删除 Zep 连接「${connection.name}」？\n该密钥将从本机配置移除；Zep 上的图谱不会被删除。`)) return
  await runAction(`delete-zep-${connection.id}`, async () => { const data = await studioApi.removeZep(connection.id, lifetime.signal); if (zepForm.id === connection.id) newZep(); await refreshCore(); return data }, 'Zep 连接已删除。')
}

async function toggleRotation() {
  const next = !config.auto_zep
  await runAction('rotation', async () => { const data = await studioApi.saveSettings({ auto_zep: next }, lifetime.signal); await refreshCore(); return data }, next ? '已开启同组 Zep 密钥自动切换。' : '已关闭 Zep 密钥自动切换。')
}

async function createBackup() {
  await runAction('create-backup', async () => { const data = await studioApi.createBackup(lifetime.signal); await loadBackups(); return data }, '记录备份已创建，并已保存到本机备份目录。')
}

async function restoreBackup(backup) {
  if (!window.confirm(`恢复备份「${backup.name}」？\n当前记录将被备份中的记录替换。恢复前会创建当前数据的回退备份。`)) return
  await runAction(`restore-${backup.name}`, async () => {
    const data = await studioApi.restoreBackup(backup.name, lifetime.signal)
    await Promise.allSettled([refreshCore(), loadRecords(), loadBackups()])
    const notes = Array.isArray(data?.restore_notes) ? data.restore_notes.filter(item => typeof item === 'string') : typeof data?.restore_notes === 'string' ? [data.restore_notes] : []
    const missing = data?.missing_zep_profile_ids?.length || 0
    if (missing) notes.push(`有 ${missing} 条 Zep 连接尚未配置。请补充对应项目的连接后再使用相关图谱。`)
    return { ...data, persistent_notice: notes.length > 0, message: [data?.message || '记录已恢复。启动引擎后可以查看。', ...notes].join('\n') }
  }, '记录已恢复。启动引擎后可以查看。')
}

function openRecord(project) {
  if (!engineReady.value) return
  if (project.report_id) router.push(`/report/${encodeURIComponent(project.report_id)}`)
  else if (project.simulation_id) {
    const hasRun = project.simulation_run_status && project.simulation_run_status !== 'idle'
    router.push(`/simulation/${encodeURIComponent(project.simulation_id)}${hasRun ? '/start' : ''}`)
  }
  else if (project.project_id) router.push(`/process/${encodeURIComponent(project.project_id)}`)
}

function endpointLabel(value) { try { return new URL(value).host } catch { return value || '自定义服务' } }
function formatDate(value) { if (!value) return '时间未知'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '时间未知' : new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date) }
function formatSize(value) { const bytes = Number(value); if (!Number.isFinite(bytes)) return '大小未知'; if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`; if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`; return `${(bytes / 1024 ** 3).toFixed(1)} GB` }
function formatUptime(value) { const minutes = Math.floor(Number(value) / 60); if (minutes < 1) return '不足 1 分钟'; if (minutes < 60) return `${minutes} 分钟`; return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟` }
function formatLatency(value) { return Number(value) >= 1000 ? `${(Number(value) / 1000).toFixed(1)} 秒` : `${Math.round(Number(value))} 毫秒` }
function recordStatus(value) { return ({ created: '已创建', pending: '等待开始', init: '已创建', initialized: '已创建', uploaded: '材料已上传', ontology_generated: '本体已生成', graph_building: '构建图谱中', graph_completed: '图谱已就绪', preparing: '准备中', ready: '已就绪', running: '推演中', completed: '已完成', stopped: '已停止', failed: '需要处理', error: '需要处理', reporting: '生成报告中', report_completed: '报告已生成' })[value] || value || '已保存' }

onMounted(async () => { await refreshAll(); if (!disposed) pollTimer = window.setTimeout(poll, 5000) })
onBeforeUnmount(() => { disposed = true; lifetime.abort(); window.clearTimeout(pollTimer); window.clearTimeout(noticeTimer); modelForm.key = ''; zepForm.key = '' })
</script>

<style scoped>
.quit-studio { display:flex; gap:9px; align-items:center; padding:10px 14px; margin-bottom:16px; border:1px solid #365044; border-radius:7px; background:transparent; color:#c2d4c7; width:100%; font-size:12px!important; }
.quit-studio:hover { background:#284337; }
.studio-shell { --canvas: #f6f7f5; --surface: #fff; --forest: #152824; --primary: #147d64; --primary-hover: #106b55; --ink: #20332c; --muted: #65766e; --line: #e1e7e1; --soft: #edf4ee; --success: #126149; --danger: #ad3d35; --radius: 17px; min-height: 100vh; background: var(--canvas); color: var(--ink); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 14px; line-height: 1.55; display: flex; }
.studio-shell *, .studio-shell *::before, .studio-shell *::after { box-sizing: border-box; }
.studio-shell button, .studio-shell input, .studio-shell select { font: inherit; }
.studio-shell button { cursor: pointer; }
.studio-shell :is(button, a) { touch-action: manipulation; }
.studio-shell button:disabled { cursor: not-allowed; opacity: .5; }
.studio-shell button, .studio-shell a, .studio-shell input, .studio-shell select, .studio-shell summary { -webkit-tap-highlight-color: transparent; }
.studio-shell :is(button, a, input, select, summary):focus-visible { outline: 3px solid #459e85; outline-offset: 3px; }
.studio-shell h1, .studio-shell h2, .studio-shell h3, .studio-shell p { margin: 0; }
.studio-shell h2 { font-size: 17px; font-weight: 650; letter-spacing: -.3px; }
.studio-shell h3 { font-size: 16px; font-weight: 650; }
.skip-link { position: fixed; z-index: 100; top: -60px; left: 24px; padding: 12px 18px; border-radius: 8px; background: white; color: var(--primary); box-shadow: 0 4px 16px #0003; font-size: 14px; }
.skip-link:focus { top: 14px; }
.studio-sidebar { width: 232px; flex: 0 0 232px; position: fixed; inset: 0 auto 0 0; z-index: 20; display: flex; flex-direction: column; background: var(--forest); color: #ecf1e9; padding: 34px 19px 22px; }
.studio-brand { display: flex; align-items: center; gap: 12px; padding: 0 10px; color: inherit; text-decoration: none; width: fit-content; }
.brand-symbol { display: grid; place-items: center; width: 39px; height: 43px; color: #c9e5b2; }
.brand-symbol .studio-icon { width: 36px; height: 36px; stroke-width: 1.3; }
.brand-type { font-size: 23px; font-weight: 650; letter-spacing: -.8px; line-height: 1.2; }
.brand-type > span { display: flex; align-items: center; gap: 10px; margin-top: 6px; color: #aac0b2; font-size: 12px; letter-spacing: 3.1px; font-weight: 500; }
.brand-type i { color: #c6d8ca; background: #2b4039; border-radius: 4px; padding: 2px 5px; letter-spacing: .3px; font-style: normal; font-size: 11px; }
.sidebar-label { margin: 49px 14px 15px; color: #a9bcb0; font-size: 12px; letter-spacing: 1.5px; }
.studio-nav { display: grid; gap: 8px; }
.studio-nav button { border: 1px solid transparent; background: transparent; display: flex; align-items: center; gap: 13px; min-height: 50px; width: 100%; padding: 0 14px; color: #b9cac0; font-size: 14px; border-radius: 10px; text-align: left; transition: background .2s, color .2s, border-color .2s; }
.studio-nav button:hover { background: #233b33; color: #fff; }
.studio-nav button.active { color: #eff8e8; background: #2c4639; border-color: #3b5746; }
.studio-nav button.active > .studio-icon:first-child { color: #c3dfac; }
.nav-arrow { margin-left: auto; width: 15px; height: 15px; color: #c3d9b8; }
.sidebar-bottom { margin-top: auto; padding: 24px 11px 0; }
.sidebar-note { display: flex; gap: 11px; color: #ccdace; font-size: 12px; align-items: center; padding-bottom: 24px; }
.sidebar-note > .studio-icon { width: 22px; height: 22px; color: #a3bd9f; }
.sidebar-note small { display: inline-block; margin-top: 4px; font-size: 12px; color: #a5b7a9; }
.studio-connection { border-top: 1px solid #35483d; padding-top: 18px; font-size: 12px; color: #adbfaf; display: flex; align-items: center; gap: 8px; }
.studio-main { min-width: 0; flex: 1; margin-left: 232px; }
.topbar { min-height: 75px; padding: 0 40px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--line); background: #fbfcfa; gap: 16px; }
.breadcrumb { font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 14px; }
.breadcrumb span { color: #b3bdb5; }
.breadcrumb strong { font-weight: 500; color: var(--ink); }
.topbar-actions { display: flex; gap: 16px; align-items: center; }
.version-pill { font-size: 12px; color: var(--muted); letter-spacing: .5px; }
.workspace { max-width: 1500px; padding: 38px 40px 24px; margin: 0 auto; }
.page-heading { display: flex; justify-content: space-between; align-items: center; gap: 24px; margin-bottom: 31px; }
.eyebrow { color: var(--primary); font-size: 12px; font-weight: 700; letter-spacing: 2px; margin-bottom: 13px !important; }
.page-heading h1 { font-size: clamp(24px, 2.25vw, 33px); font-weight: 650; letter-spacing: -1.05px; line-height: 1.35; }
.page-description { font-size: 13px; color: var(--muted); margin-top: 11px !important; line-height: 1.75; }
.button { min-height: 43px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; border: 1px solid transparent; border-radius: 8px; padding: 10px 17px; font-size: 13px !important; font-weight: 550 !important; line-height: 1.4; text-decoration: none; white-space: nowrap; transition: background .18s, border-color .18s, box-shadow .18s; }
.button .studio-icon { width: 17px; height: 17px; }
.button-primary { background: var(--primary); border-color: var(--primary); color: #fff; box-shadow: 0 3px 6px #12614910; }
.button-primary:hover:not(:disabled) { background: var(--primary-hover); border-color: var(--primary-hover); box-shadow: 0 4px 12px #12614924; }
.button-soft { color: var(--success); background: var(--soft); border-color: #e0eadf; }
.button-soft:hover:not(:disabled) { background: #e0eddf; border-color: #cbddce; }
.button-outline { background: #fff; border-color: #dce4dd; color: #43564a; }
.button-outline:hover:not(:disabled) { background: #f2f6f1; border-color: #b5c7b8; }
.button-small { min-height: 38px; padding: 8px 13px; font-size: 12px !important; }
.icon-button { border: 0; background: transparent; display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 7px; color: var(--muted); transition: background .18s, color .18s; flex-shrink: 0; }
.icon-button .studio-icon { width: 17px; height: 17px; }
.icon-button:hover:not(:disabled) { background: #eaf0e9; color: var(--primary); }
.danger-icon:hover:not(:disabled) { background: #fbeeea; color: var(--danger); }
.text-button { border: 0; background: none; display: inline-flex; gap: 7px; align-items: center; padding: 5px 0; color: var(--primary); font-size: 12px !important; font-weight: 600 !important; min-height: 32px; white-space: nowrap; }
.text-button:hover:not(:disabled) { color: #074d3a; text-decoration: underline; text-underline-offset: 3px; }
.text-button .studio-icon { width: 16px; height: 16px; }
.surface { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: 0 3px 9px #29382a03; }
.dashboard-top { display: grid; grid-template-columns: minmax(0, 1.75fr) minmax(295px, 1fr); gap: 22px; }
.launch-card { position: relative; isolation: isolate; overflow: hidden; min-height: 322px; border: 1px solid #dce6d6; border-radius: var(--radius); background: #edf2e8; padding: 27px 31px 22px; display: grid; grid-template-columns: 1fr; }
.section-kicker { display: flex; align-items: center; gap: 7px; color: #657b61; font-size: 12px; letter-spacing: 1.5px; font-weight: 600; }
.tiny-square { width: 5px; height: 5px; background: #8aa178; }
.launch-copy h2 { margin: 16px 0 8px; font-size: 25px; font-weight: 600; letter-spacing: -.6px; }
.launch-copy p { font-size: 12px; line-height: 1.85; color: #66735f; }
.launch-orbit { position: absolute; z-index: -1; width: 210px; height: 210px; right: -27px; top: -7px; border-radius: 50%; border: 1px solid #d3dfc9; display: grid; place-items: center; opacity: .95; }
.launch-orbit > div { border: 1px solid #d3dfc9; border-radius: 50%; position: absolute; }
.launch-orbit > div:first-child { width: 156px; height: 156px; }
.launch-orbit > div:nth-child(2) { width: 106px; height: 106px; }
.launch-orbit > span { width: 58px; height: 58px; border-radius: 50%; background: #dae6cf; display: grid; place-items: center; color: #80986b; }
.launch-orbit .studio-icon { width: 35px; height: 35px; stroke-width: 1; }
.setup-steps { display: flex; align-items: stretch; gap: 0; background: #ffffffc2; border: 1px solid #dce5d5; border-radius: 11px; margin-top: 27px; padding: 14px 0; position: relative; }
.setup-step { border: 0; border-right: 1px solid #dee5d8; display: flex; align-items: flex-start; gap: 7px; background: transparent; flex: 1; color: var(--ink); text-align: left; padding: 3px 11px; min-width: 0; transition: background .18s; }
.setup-step > span:nth-child(2) { min-width: 0; flex: 1; }
.setup-step:last-child { border-right: 0; }
.setup-step:hover:not(:disabled) { background: #e8efe1; }
.step-number { color: #8a9780; font-size: 12px; line-height: 20px; letter-spacing: .5px; font-weight: 600; }
.step-number .studio-icon { width: 16px; height: 16px; color: var(--primary); }
.setup-step strong { display: block; font-size: 12px; font-weight: 650; line-height: 21px; }
.setup-step small { display: block; margin-top: 4px; font-size: 12px; color: var(--muted); line-height: 1.5; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.setup-step > .studio-icon:last-child { width: 13px; height: 13px; margin-left: auto; margin-top: 4px; color: #9daa92; display: none; }
.engine-card { padding: 22px 24px 16px; display: flex; flex-direction: column; }
.section-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.badge { display: inline-flex; gap: 5px; align-items: center; justify-content: center; font-size: 12px; font-weight: 500; border: 1px solid transparent; border-radius: 5px; padding: 4px 7px; white-space: nowrap; line-height: 1.5; flex-shrink: 0; }
.badge .studio-icon { width: 12px; height: 12px; }
.badge-green { background: #edf5ec; color: #3c7044; border-color: #e0ebdb; }
.badge-neutral { background: #f2f4f0; color: #6b7766; border-color: #e8ece4; }
.badge-red { background: #fdf0ec; color: #ad493d; border-color: #f3ddd4; }
.status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #a6b3a2; flex-shrink: 0; }
.status-dot.good { background: #5d9b60; }
.status-dot.muted { background: #a5afa3; }
.engine-visual { display: flex; align-items: center; gap: 10px; margin: 28px 0 11px; font-size: 19px; font-weight: 600; letter-spacing: -.4px; }
.engine-visual .studio-icon { height: 34px; width: 34px; padding: 8px; box-sizing: content-box; border-radius: 13px; background: #f1f4ee; color: #7b8e72; }
.engine-visual.ready .studio-icon { background: #eaf4e7; color: #54813c; }
.engine-message { color: var(--muted); font-size: 12px; line-height: 1.7; min-height: 38px; overflow-wrap: anywhere; }
.inline-info { display: flex; gap: 6px; color: #6f7f62; font-size: 12px; padding: 7px 0; }
.inline-info .studio-icon { width: 14px; height: 14px; }
.engine-controls { display: flex; gap: 9px; margin-top: 15px; }
.engine-controls > .button { flex: 1; min-height: 37px; font-size: 12px !important; padding: 8px 12px; }
.engine-controls > .button .studio-icon { width: 14px; height: 14px; }
.engine-foot { display: flex; justify-content: space-between; gap: 8px; margin-top: auto; padding-top: 18px; color: var(--muted); font-size: 12px; }
.stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px; margin-top: 23px; }
.stat-card { padding: 22px 23px; display: flex; align-items: center; gap: 17px; }
.stat-icon { display: grid; place-items: center; width: 43px; height: 43px; border-radius: 11px; background: #f2f5ef; color: #708163; }
.stat-icon .studio-icon { width: 20px; height: 20px; }
.stat-label { display: block; font-size: 12px; color: var(--muted); }
.stat-card strong { display: block; font-size: 27px; line-height: 1.15; font-weight: 550; letter-spacing: -.8px; margin-top: 8px; }
.stat-caption { font-size: 12px; color: var(--muted); margin-left: auto; align-self: flex-end; padding-bottom: 4px; white-space: nowrap; }
.dashboard-bottom { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 22px; margin-top: 23px; }
.recent-card, .current-card { padding: 23px 25px; }
.recent-card > .section-title, .current-card > .section-title { margin-bottom: 16px; }
.recent-row { width: 100%; display: flex; align-items: center; gap: 13px; text-align: left; padding: 15px 0; border: 0; background: transparent; border-top: 1px solid #f0f3ec; color: var(--ink); transition: background .18s; }
.recent-row:hover:not(:disabled) { background: #f7faf4; }
.recent-row:first-child { border-top: 0; }
.record-icon { display: grid; place-items: center; width: 36px; height: 38px; border-radius: 8px; background: #f3f5f0; color: #73866b; flex-shrink: 0; }
.record-icon .studio-icon { width: 18px; height: 18px; }
.recent-main { min-width: 0; flex: 1; }
.recent-main strong { display: block; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-main small { display: block; font-size: 12px; color: var(--muted); margin-top: 4px; }
.recent-row > .studio-icon:last-child { width: 14px; height: 14px; color: #8fa184; }
.quiet-label { font-size: 12px; color: var(--muted); }
.current-config { background: transparent; width: 100%; display: flex; align-items: center; gap: 12px; border: 0; border-bottom: 1px solid #eff2eb; text-align: left; color: var(--ink); padding: 16px 0; transition: background .18s; }
.current-config:hover { background: #f7faf4; }
.current-config > span:nth-child(2) { min-width: 0; flex: 1; }
.config-icon { background: #f2f6ee; color: #6e8361; width: 35px; height: 35px; border-radius: 8px; display: grid; place-items: center; flex-shrink: 0; }
.config-icon .studio-icon { width: 18px; height: 18px; }
.current-config small { display: block; color: var(--muted); font-size: 12px; }
.current-config strong { display: block; font-size: 12px; font-weight: 600; margin-top: 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.current-config em { display: block; font-size: 12px; font-style: normal; color: var(--muted); margin-top: 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.current-config > .studio-icon:last-child { width: 14px; height: 14px; color: #8fa184; }
.local-note { display: flex; gap: 7px; margin-top: 17px; align-items: flex-start; color: var(--muted); }
.local-note .studio-icon { width: 14px; height: 14px; margin-top: 2px; }
.local-note p { font-size: 12px; line-height: 1.75; }
.empty-state { padding: 46px 24px; display: flex; flex-direction: column; align-items: center; text-align: center; color: var(--muted); }
.empty-state.compact { padding: 22px 16px; }
.empty-state .empty-icon { display: grid; place-items: center; background: #f2f5ed; color: #8a9e7a; border-radius: 13px; width: 52px; height: 52px; margin-bottom: 16px; }
.empty-icon > .studio-icon { width: 25px; height: 25px; stroke-width: 1.5; }
.empty-state h3 { color: #58694e; font-size: 14px; font-weight: 600; }
.empty-state p { font-size: 12px; line-height: 1.8; margin-top: 8px; max-width: 480px; }
.empty-state .text-button { margin-top: 11px; }
.empty-state > .studio-icon { color: #8fa080; }
.tall-empty { min-height: 310px; justify-content: center; }
.empty-tip { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--muted); margin-top: 26px; }
.empty-tip .studio-icon { width: 14px; height: 14px; }
.logs-panel { margin-top: 22px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.logs-panel summary { display: flex; justify-content: space-between; align-items: center; color: #6c7d62; padding: 15px 1px; font-size: 12px; cursor: pointer; list-style: none; }
.logs-panel summary::-webkit-details-marker { display: none; }
.logs-panel summary > span { display: inline-flex; align-items: center; gap: 8px; }
.logs-panel summary .studio-icon { width: 15px; height: 15px; }
.logs-panel[open] summary > span:last-child .studio-icon { transform: rotate(90deg); }
.logs-toolbar { display: flex; align-items: center; justify-content: space-between; color: var(--muted); font-size: 12px; }
.log-output { margin: 0 0 17px; max-height: 330px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: #1d2e24; color: #d0dec5; border-radius: 9px; padding: 17px; font: 12px/1.8 Consolas, "Microsoft YaHei", monospace; }
.workspace-footer { display: flex; align-items: center; gap: 12px; color: var(--muted); font-size: 12px; padding: 30px 0 0; }
.workspace-footer > span:first-child { color: #687b5a; font-weight: 600; }
.workspace-footer > span:nth-child(2) { padding-left: 12px; border-left: 1px solid #d9e1d2; }
.footer-local { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.alert { display: flex; align-items: flex-start; gap: 10px; padding: 14px 16px; border-radius: 10px; margin-bottom: 20px; border: 1px solid; font-size: 12px; line-height: 1.7; }
.alert > .studio-icon { width: 18px; height: 18px; margin-top: 2px; }
.alert p { flex: 1; overflow-wrap: anywhere; }
.alert-error { background: #fff2ed; border-color: #efd8cd; color: #9b4233; }
.alert-success { background: #eef7ea; border-color: #d6e6cb; color: #44703a; }
.alert-info { background: #edf4ec; border-color: #dbe6d4; color: #527447; }
.notice { position: relative; align-items: center; }
.notice p { white-space: pre-line; }
.notice .icon-button { width: 26px; height: 26px; margin: -3px -4px -3px auto; color: inherit; }
.connection-alert { align-items: center; }
.connection-alert > div { flex: 1; }
.connection-alert strong { font-weight: 600; }
.connection-alert p { font-size: 12px; margin-top: 2px; }
.config-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(330px, 420px); align-items: start; gap: 30px; }
.list-heading { min-height: 40px; display: flex; align-items: center; justify-content: space-between; margin-bottom: 13px; gap: 12px; }
.list-heading h2 { font-size: 15px; }
.list-heading h2 > span, .count-label { display: inline-block; font-size: 12px; font-weight: 500; min-width: 21px; text-align: center; background: #e7eee0; color: #5c7649; border-radius: 5px; padding: 2px 5px; margin-left: 6px; vertical-align: middle; }
.preset-card { margin-bottom: 15px; padding: 21px 23px 16px; transition: border-color .18s, box-shadow .18s; }
.preset-card.selected { border-color: #91bba2; box-shadow: 0 0 0 1px #91bba20a, 0 4px 15px #5c7b4b08; }
.preset-card.editing { outline: 2px solid #d6e3cc; outline-offset: 3px; }
.preset-top { display: flex; gap: 12px; align-items: center; }
.preset-icon { background: #f0f5eb; color: #728b5c; border-radius: 10px; display: grid; place-items: center; width: 42px; height: 42px; flex-shrink: 0; }
.preset-title { min-width: 0; flex: 1; }
.preset-title h3 { overflow-wrap: anywhere; font-size: 15px; }
.preset-title > span { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.model-name { display: inline-block; max-width: 100%; margin-top: 21px; font-size: 12px; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; color: #4a6644; background: #f4f7f0; border: 1px solid #e7eddf; padding: 6px 10px; border-radius: 6px; overflow-wrap: anywhere; }
.preset-details { margin: 14px 0 17px; display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--muted); }
.preset-details > span { display: flex; align-items: center; gap: 6px; }
.preset-actions { display: flex; align-items: center; justify-content: space-between; padding-top: 13px; border-top: 1px solid #edf1e7; gap: 12px; }
.preset-actions > div { display: flex; gap: 3px; }
.section-footnote { display: flex; gap: 7px; font-size: 12px; color: var(--muted); line-height: 1.8; margin-top: 20px !important; }
.section-footnote .studio-icon { width: 15px; height: 15px; margin-top: 3px; }
.editor-panel { padding: 25px 25px 21px; position: sticky; top: 24px; }
.editor-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 25px; gap: 16px; }
.editor-title h2 { font-size: 19px; margin-top: 7px; }
.editor-title .section-kicker { color: var(--muted); font-size: 11px; }
.editor-panel fieldset { border: 0; min-width: 0; padding: 0; margin: 0; }
.form-field { margin-bottom: 19px; }
.form-field label { display: inline-block; color: #4a6140; font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.optional { font-size: 12px; font-weight: 400; color: var(--muted); margin-left: 5px; }
.field-en { color: var(--muted); font-size: 12px; margin-left: 5px; font-weight: 400; }
.form-field :is(input, select) { display: block; width: 100%; color: var(--ink); background: #fbfcf9; border: 1px solid #dce4d5; border-radius: 7px; padding: 11px 12px; min-height: 44px; outline: none; font-size: 12px; transition: border-color .18s, box-shadow .18s; }
.form-field :is(input, select):focus { border-color: #7ead84; box-shadow: 0 0 0 3px #75a87913; background: #fff; }
.form-field :is(input, select):disabled { opacity: .65; cursor: wait; }
.form-field input::placeholder { color: #9aa68f; font-size: 12px; }
.form-field select { color: #667859; cursor: pointer; }
.field-help { font-size: 12px; line-height: 1.75; color: var(--muted); margin-top: 7px !important; }
.input-with-button { position: relative; }
.input-with-button input { padding-right: 43px; }
.input-with-button .icon-button { position: absolute; right: 3px; top: 3px; height: 38px; width: 36px; }
.saved-label { font-size: 11px; color: #64905a; background: #edf5e8; padding: 2px 5px; border-radius: 3px; margin-left: 6px; font-weight: 500; }
.field-label-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; }
.field-label-row label { margin: 0; }
.field-label-row .text-button { font-size: 12px !important; padding: 0; min-height: 20px; }
.field-label-row .studio-icon { width: 12px; height: 12px; }
.form-actions { display: flex; gap: 10px; margin-top: 24px; }
.form-actions .button { flex: 1; padding: 10px 12px; font-size: 12px !important; }
.form-footer { color: var(--muted); font-size: 12px; margin-top: 15px !important; line-height: 1.8; text-align: center; }
.form-feedback { border-radius: 7px; padding: 10px 11px; display: flex; align-items: flex-start; gap: 7px; font-size: 12px; line-height: 1.75; background: #eef5e9; color: #4f7640; overflow-wrap: anywhere; }
.form-feedback .studio-icon { width: 14px; height: 14px; margin-top: 3px; }
.form-feedback.error { background: #fff0e9; color: #a3523b; }
.form-feedback.info { background: #f1f4ea; color: #79805f; }
.rotation-card { padding: 23px 26px; display: flex; gap: 20px; align-items: center; margin-bottom: 28px; background: #f0f6ec; border-color: #dbe8d1; }
.rotation-icon { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 12px; background: #e2edda; color: #66964b; flex-shrink: 0; }
.rotation-copy { flex: 1; }
.rotation-copy > div { display: flex; align-items: center; gap: 12px; }
.rotation-copy h2 { font-size: 16px; }
.rotation-copy p { color: #768b66; margin-top: 7px; font-size: 12px; line-height: 1.7; }
.switch { display: inline-flex; align-items: center; width: 46px; height: 28px; border: 1px solid #c6d4bd; background: #cbd9c3; border-radius: 99px; padding: 3px; transition: background .2s, border-color .2s; flex-shrink: 0; }
.switch span { width: 20px; height: 20px; background: white; border-radius: 50%; box-shadow: 0 1px 3px #30492122; transform: translateX(0); transition: transform .2s; }
.switch.on { background: var(--primary); border-color: var(--primary); }
.switch.on span { transform: translateX(17px); }
.key-summary { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12px; margin: 22px 0 17px; letter-spacing: .2px; }
.key-summary .studio-icon { width: 15px; height: 15px; }
.group-explainer { display: flex; align-items: flex-start; gap: 10px; margin: 21px 0 0; border-radius: 9px; padding: 16px; background: #eaf0e3; color: #687f55; }
.group-explainer > .studio-icon { width: 18px; height: 18px; margin-top: 2px; }
.group-explainer strong { font-size: 12px; font-weight: 600; }
.group-explainer p { font-size: 12px; margin-top: 6px; line-height: 1.85; }
.checkbox-label { display: flex; align-items: flex-start; gap: 9px; cursor: pointer; font-size: 12px; color: #5e7650; margin: 23px 0 3px; }
.checkbox-label input { width: 17px; height: 17px; margin-top: 2px; accent-color: var(--primary); cursor: pointer; }
.checkbox-label small { display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }
.records-panel, .backups-panel { padding: 25px 26px; margin-bottom: 24px; }
.records-panel > .section-title { margin-bottom: 18px; }
.search-field { display: flex; align-items: center; gap: 8px; border: 1px solid #e0e7d9; padding: 7px 11px; border-radius: 7px; color: #8a9b79; background: #fafcf7; }
.search-field .studio-icon { width: 15px; height: 15px; }
.search-field input { border: 0; outline: none; background: transparent; width: 150px; max-width: 100%; font-size: 12px; color: var(--ink); min-height: 25px; }
.search-field input::placeholder { color: #96a387; }
.table-scroll { overflow-x: auto; }
.records-table { width: 100%; border-collapse: collapse; text-align: left; }
.records-table thead { color: var(--muted); font-size: 12px; }
.records-table th { font-weight: 500; padding: 9px 12px 13px; border-bottom: 1px solid #e8eee1; white-space: nowrap; }
.records-table td { padding: 16px 12px; border-bottom: 1px solid #edf2e6; font-size: 12px; color: var(--muted); vertical-align: middle; }
.records-table th:first-child, .records-table td:first-child { padding-left: 0; }
.records-table th:last-child, .records-table td:last-child { padding-right: 0; text-align: right; }
.records-table tbody tr:last-child td { border-bottom: 0; }
.records-table td:nth-child(2) { white-space: nowrap; }
.table-project { display: flex; align-items: center; gap: 12px; max-width: 440px; min-width: 175px; }
.table-project strong { color: #405d34; font-size: 12px; font-weight: 550; display: block; overflow-wrap: anywhere; }
.table-project small { display: block; font-size: 12px; color: var(--muted); margin-top: 5px; }
.card-bottom-note { font-size: 12px; color: var(--muted); padding-top: 13px; border-top: 1px solid #edf1e8; }
.section-subtitle { font-size: 12px; color: var(--muted); margin-top: 6px !important; }
.backup-list { margin-top: 19px; }
.backup-row { display: flex; align-items: center; gap: 13px; padding: 17px 0; border-bottom: 1px solid #edf2e6; }
.backup-row:last-child { border-bottom: 0; }
.backup-file-icon { width: 39px; height: 42px; display: grid; place-items: center; background: #f0f5e9; color: #819a69; border-radius: 8px; flex-shrink: 0; }
.backup-details { min-width: 0; flex: 1; }
.backup-details strong { display: block; color: #506b41; font-size: 12px; font-weight: 500; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
.backup-details small { display: block; font-size: 12px; color: var(--muted); margin-top: 6px; }
.backup-details small > span { padding: 0 5px; }
.backup-row .button { font-size: 12px !important; }
.backup-guidance { margin-top: 17px; padding: 16px; border: 1px solid #e4ebdc; border-radius: 9px; display: flex; gap: 10px; background: #f8faf4; color: var(--muted); }
.backup-guidance .studio-icon { width: 16px; height: 16px; margin-top: 2px; }
.backup-guidance > div { min-width: 0; }
.backup-guidance p { font-size: 12px; line-height: 1.9; }
.path-note { margin-top: 5px !important; }
.path-note code { font-family: inherit; word-break: break-all; font-size: 12px; color: var(--muted); margin-left: 5px; }
.spinning { animation: studio-spin 1.1s linear infinite; }
@keyframes studio-spin { to { transform: rotate(360deg); } }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@media (min-width: 1600px) { .workspace { padding-top: 48px; } .launch-card { min-height: 350px; } .launch-copy h2 { font-size: 28px; } .launch-copy p { font-size: 13px; } .setup-step strong { font-size: 12px; } .setup-step small { font-size: 12px; } .setup-step { padding-left: 18px; padding-right: 18px; } .launch-orbit { right: 30px; top: 10px; } }
@media (max-width: 1200px) { .studio-sidebar { width: 205px; flex-basis: 205px; padding-left: 13px; padding-right: 13px; } .studio-main { margin-left: 205px; } .workspace { padding: 31px 26px 23px; } .topbar { padding-left: 26px; padding-right: 26px; } .dashboard-top { grid-template-columns: minmax(0, 1.35fr) minmax(270px, 1fr); gap: 18px; } .launch-card { padding: 25px 22px 22px; } .launch-orbit { right: -97px; opacity: .6; } .launch-copy h2 { font-size: 22px; } .setup-steps { flex-direction: column; padding: 0 12px; margin-top: 21px; } .setup-step { padding: 11px 2px; border-right: 0; border-bottom: 1px solid #e0e7d7; align-items: center; } .setup-step:last-child { border-bottom: 0; } .setup-step small { margin-top: 0; display: inline-block; margin-left: 10px; max-width: 158px; vertical-align: middle; } .setup-step strong { display: inline-block; font-size: 12px; vertical-align: middle; } .step-number { width: 18px; } .setup-step > .studio-icon:last-child { margin-top: 0; } .engine-card { padding: 21px 21px 16px; } .engine-visual { margin-top: 29px; font-size: 18px; } .stat-grid, .dashboard-bottom { gap: 18px; } .stat-card { padding: 20px 18px; gap: 12px; } .stat-caption { display: none; } .dashboard-bottom { grid-template-columns: minmax(0, 1.35fr) minmax(260px, 1fr); } .recent-card, .current-card { padding: 22px 20px; } .config-layout { grid-template-columns: minmax(0, 1fr) minmax(310px, 355px); gap: 23px; } .editor-panel { padding: 23px 21px 19px; } .preset-card { padding: 20px 18px 15px; } .preset-top { flex-wrap: wrap; gap: 10px; } .preset-top > .badge { margin-left: auto; } .preset-title h3 { font-size: 14px; } .page-heading { gap: 18px; } .page-heading > .button { padding-left: 13px; padding-right: 13px; font-size: 12px !important; } }
@media (max-width: 980px) { .studio-sidebar { width: 82px; flex-basis: 82px; padding: 29px 12px 20px; } .studio-main { margin-left: 82px; } .studio-brand { padding: 0; margin: 0 auto; } .brand-type, .sidebar-label, .studio-nav button > span, .nav-arrow, .sidebar-note, .studio-connection { display: none; } .studio-nav { margin-top: 44px; gap: 12px; } .studio-nav button { min-height: 50px; justify-content: center; padding: 0; } .studio-nav button > .studio-icon { width: 21px; height: 21px; } .topbar { min-height: 65px; } .workspace { padding: 29px 24px 21px; } .page-heading h1 { font-size: 27px; } .dashboard-top { grid-template-columns: minmax(0, 1.3fr) minmax(260px, 1fr); } .dashboard-bottom { grid-template-columns: minmax(0, 1.15fr) minmax(250px, 1fr); } .setup-step small { max-width: 125px; margin-left: 4px; } .setup-step > span:nth-child(2) { min-width: 0; } .config-layout { grid-template-columns: minmax(0, 1fr) minmax(310px, 340px); gap: 20px; } }
@media (max-width: 780px) { .page-heading { align-items: flex-start; } .page-heading h1 { font-size: 25px; } .page-heading > .button { min-height: 42px; margin-top: 29px; } .page-heading > .button > .studio-icon:last-child:not(:first-child) { display: none; } .dashboard-top, .dashboard-bottom { grid-template-columns: 1fr; } .launch-card { min-height: 315px; padding: 25px 26px; } .launch-orbit { opacity: 1; right: 10px; top: -14px; } .launch-copy h2 { font-size: 25px; } .setup-steps { flex-direction: row; padding: 13px 0; } .setup-step { flex-direction: row; align-items: flex-start; border-bottom: 0; border-right: 1px solid #e0e7d7; padding: 2px 11px; } .setup-step:last-child { border-right: 0; } .setup-step strong { display: block; } .setup-step small { display: block; margin-top: 2px; margin-left: 0; max-width: 125px; font-size: 11px; } .setup-step > .studio-icon:last-child { display: none; } .engine-card { padding: 22px; } .engine-visual { margin: 17px 0 10px; } .engine-message { min-height: 0; } .engine-foot { padding-top: 13px; } .engine-controls .button { min-height: 40px; } .stat-grid { gap: 12px; } .stat-card { gap: 10px; padding: 17px 14px; } .stat-icon { width: 32px; height: 34px; border-radius: 9px; } .stat-icon .studio-icon { width: 17px; height: 17px; } .stat-label { font-size: 12px; } .stat-card strong { font-size: 24px; } .current-config { padding: 15px 0; } .config-layout { grid-template-columns: 1fr; } .editor-panel { position: static; padding: 25px; } .preset-top { flex-wrap: nowrap; } .tall-empty { min-height: 230px; } .empty-tip { display: none; } .config-list-section { min-width: 0; } .rotation-card { padding: 20px; gap: 13px; } .rotation-icon { width: 38px; height: 40px; } .rotation-copy h2 { font-size: 14px; } .rotation-copy p { font-size: 12px; } .rotation-copy > div { gap: 8px; } .workspace-footer { flex-wrap: wrap; } .records-panel, .backups-panel { padding: 22px; } .records-table th, .records-table td { padding-right: 10px; padding-left: 10px; } .recent-row { min-height: 74px; } }
@media (max-width: 580px) { .studio-shell { display: block; } .studio-sidebar { position: static; width: 100%; min-height: 0; flex-basis: auto; padding: 15px 16px 12px; display: block; } .studio-brand { margin: 0 0 0 5px; gap: 9px; } .brand-symbol { width: 29px; height: 32px; } .brand-symbol .studio-icon { width: 29px; height: 29px; } .brand-type { display: flex; align-items: baseline; gap: 8px; font-size: 20px; } .brand-type > span { display: block; font-size: 11px; letter-spacing: 2px; } .brand-type i { display: none; } .studio-nav { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 16px; } .studio-nav button { min-height: 51px; flex-direction: column; gap: 4px; border-radius: 7px; padding: 7px 1px; font-size: 12px; } .studio-nav button > span { display: block; } .studio-nav button > .studio-icon { width: 17px; height: 17px; } .studio-nav button > .nav-arrow { display: none; } .sidebar-bottom { display: none; } .studio-main { margin-left: 0; } .topbar { min-height: 52px; padding: 0 21px; } .breadcrumb { font-size: 12px; gap: 9px; } .topbar-actions { gap: 7px; } .version-pill { font-size: 11px; } .topbar .icon-button { width: 32px; height: 32px; } .workspace { padding: 28px 19px 22px; } .page-heading { flex-direction: column; gap: 16px; margin-bottom: 23px; } .page-heading h1 { font-size: 24px; letter-spacing: -.65px; } .eyebrow { font-size: 11px; letter-spacing: 1.6px; margin-bottom: 11px !important; } .page-description { font-size: 12px; margin-top: 9px !important; } .page-heading > .button { margin-top: 0; min-height: 43px; } .launch-card { padding: 23px 23px 20px; min-height: 333px; } .launch-copy h2 { font-size: 23px; } .launch-orbit { width: 180px; height: 180px; right: -80px; top: 6px; opacity: .65; } .setup-steps { flex-direction: column; padding: 0 12px; margin-top: 20px; } .setup-step { flex-direction: row; align-items: center; padding: 10px 0; border-right: 0; border-bottom: 1px solid #e0e7d7; gap: 8px; } .setup-step:last-child { border-bottom: 0; } .setup-step > .studio-icon:last-child { display: block; margin-left: auto; } .setup-step strong { display: inline-block; font-size: 12px; } .setup-step small { display: inline-block; margin: 0 0 0 6px; font-size: 11px; max-width: 133px; } .stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; margin-top: 17px; } .stat-card { flex-direction: column; align-items: flex-start; padding: 16px 15px; gap: 11px; border-radius: 12px; } .stat-icon { width: 31px; height: 31px; } .stat-card strong { font-size: 25px; margin-top: 5px; } .stat-label { font-size: 12px; } .dashboard-bottom { margin-top: 17px; gap: 17px; } .recent-card, .current-card { padding: 22px 20px; } .recent-main strong { font-size: 12px; } .recent-row { gap: 10px; } .recent-row > .badge { font-size: 11px; padding: 3px 5px; } .recent-row > .studio-icon:last-child { display: none; } .workspace-footer { gap: 8px; font-size: 11px; padding-top: 23px; } .footer-local { width: 100%; margin-left: 0; font-size: 11px; } .workspace-footer > span:nth-child(2) { padding-left: 8px; } .alert { font-size: 12px; padding: 12px; } .connection-alert { flex-wrap: wrap; } .connection-alert > div { flex: 1 1 220px; } .connection-alert .button { margin-left: 26px; } .config-layout { gap: 22px; } .list-heading h2 { font-size: 14px; } .list-heading .quiet-label { font-size: 12px; } .preset-card { padding: 20px 20px 15px; } .preset-top { gap: 10px; } .preset-icon { width: 36px; height: 38px; } .preset-top > .badge { font-size: 11px; padding: 4px 6px; } .preset-title h3 { font-size: 14px; } .editor-panel { padding: 23px 21px; } .form-field :is(input, select) { font-size: 14px; min-height: 46px; } .form-field input::placeholder { font-size: 12px; } .input-with-button .icon-button { top: 4px; } .rotation-card { gap: 12px; padding: 18px 17px; flex-wrap: wrap; } .rotation-icon { display: none; } .rotation-copy { flex: 1 1 210px; } .rotation-copy h2 { font-size: 14px; } .rotation-copy > div { gap: 8px; } .rotation-copy > div .badge { font-size: 11px; } .rotation-copy p { font-size: 12px; margin-top: 7px; } .switch { width: 43px; height: 26px; padding: 3px; } .switch span { width: 18px; height: 18px; } .switch.on span { transform: translateX(16px); } .records-panel, .backups-panel { padding: 20px 18px; } .records-panel > .section-title { align-items: flex-start; flex-direction: column; gap: 12px; } .records-panel .search-field { width: 100%; } .records-panel .search-field input { width: 100%; } .records-table { min-width: 520px; } .backup-row { flex-wrap: wrap; gap: 10px; } .backup-details { flex-basis: calc(100% - 52px); } .backup-row > .button { margin-left: 49px; min-height: 38px; } .backup-guidance { padding: 12px; gap: 8px; } .backup-guidance p { font-size: 12px; } .section-subtitle { font-size: 12px; } .empty-state p { font-size: 12px; } .empty-state h3 { font-size: 13px; } .group-explainer p { font-size: 12px; } .form-actions .button { min-height: 43px; } }
@media (prefers-reduced-motion: reduce) { .studio-shell *, .studio-shell *::before, .studio-shell *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; animation-iteration-count: 1 !important; } }
</style>
