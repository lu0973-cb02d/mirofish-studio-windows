<template>
  <div class="studio-shell">
    <a class="skip-link" href="#studio-main">跳到工作台内容</a>
    <aside class="studio-sidebar" aria-label="工作台导航">
      <router-link class="studio-brand" to="/" aria-label="MiroFish Studio 工作台">
        <span class="brand-symbol"><Icon name="spark" /></span>
        <span class="brand-type">MiroFish<span>STUDIO <i>v{{ status.version || '1.1.0' }}</i></span></span>
      </router-link>
      <div class="sidebar-label">工作空间</div>
      <nav class="studio-nav">
        <button v-for="item in navigation" :key="item.id" type="button" :class="{ active: tab === item.id }" :aria-label="item.name" :title="item.name" :aria-current="tab === item.id ? 'page' : undefined" @click="setTab(item.id)">
          <Icon :name="item.icon" /><span>{{ item.name }}</span><Icon v-if="tab === item.id" class="nav-arrow" name="chevron" />
        </button>
      </nav>
      <div class="sidebar-bottom">
        <button class="quit-studio" :disabled="!!action || status.busy || !connected" @click="quitStudio"><Icon name="power" /><span>退出工作台</span></button>
        <div class="sidebar-note"><Icon name="shield" /><span>本机配置与记录<small>密钥加密保存</small></span></div>
        <div class="studio-connection"><span class="status-dot" :class="{ good: connected, muted: !connected }"></span>{{ connected ? '本地工作台已连接' : initialLoading ? '正在连接工作台' : '工作台连接中断' }}</div>
      </div>
    </aside>

    <main id="studio-main" class="studio-main" tabindex="-1">
      <header class="topbar">
        <div class="breadcrumb">本地工作台 <span>/</span> <strong>{{ currentNavigation.name }}</strong></div>
        <div class="topbar-actions"><span class="topbar-status"><span class="status-dot" :class="connected ? 'good' : 'muted'"></span>{{ connected ? '本地服务已连接' : initialLoading ? '正在连接' : '连接中断' }}</span><span class="version-pill">v{{ status.version || '1.1.0' }}</span><button class="icon-button" type="button" aria-label="刷新工作台状态" title="刷新状态" :disabled="refreshing" @click="refreshAll"><Icon name="refresh" :class="{ spinning: refreshing }" /></button></div>
      </header>

      <div class="workspace">
        <Transition name="feedback" mode="out-in">
          <div v-if="closedByUser" key="closed" class="alert alert-success" role="status"><Icon name="check" /><p>工作台已退出，配置与记录已保留。再次使用时双击桌面上的「MiroFish 工作台」。</p></div>
          <div v-else-if="!connected && !initialLoading" key="disconnected" class="alert alert-error connection-alert" role="alert"><Icon name="info" /><div><strong>暂时无法连接本地工作台</strong><p>{{ connectionError }}</p></div><button class="button button-small button-soft" :disabled="refreshing" @click="refreshAll">重新连接</button></div>
        </Transition>
        <Transition name="feedback" mode="out-in">
          <div v-if="notice" :key="notice.message" class="alert notice" :class="notice.type === 'error' ? 'alert-error' : 'alert-success'" :role="notice.type === 'error' ? 'alert' : 'status'"><Icon :name="notice.type === 'error' ? 'info' : 'check'" /><p>{{ notice.message }}</p><button class="icon-button" type="button" aria-label="关闭提示" @click="notice = null"><Icon name="close" /></button></div>
        </Transition>

        <Transition name="workspace-pane" mode="out-in" appear>
        <div :key="tab" class="tab-pane" :aria-label="currentNavigation.name">
        <template v-if="tab === 'dashboard'">
          <section class="page-heading">
            <div><h1>工作台</h1><p class="page-description">管理运行状态、当前配置和最近的推演。</p></div>
            <button class="button button-primary" :disabled="initialLoading || !!action || !connected" @click="primaryAction"><Icon :name="primaryActionIcon" />{{ primaryActionLabel }}<Icon name="arrow" /></button>
          </section>

          <div class="dashboard-top">
            <section class="launch-card">
              <div class="launch-copy"><div><span class="section-kicker">运行准备</span><h2>{{ canCreate ? '配置已就绪' : '确认配置，开始推演' }}</h2><p>模型、记忆连接与引擎状态，一目了然。</p></div><span class="setup-summary" :class="{ ready: canCreate }"><strong>{{ Number(modelReady) + Number(zepReady) + Number(engineReady) }}<small>/ 3</small></strong><span>已就绪</span></span></div>
              <div class="setup-steps">
                <button class="setup-step" :class="{ complete: modelReady }" @click="setTab('models')"><span class="step-number"><Icon v-if="modelReady" name="check" /><template v-else>01</template></span><span><strong>选择 AI 模型</strong><small>{{ modelReady ? activeModel.name : '保存地址、密钥与模型' }}</small></span><Icon name="chevron" /></button>
                <button class="setup-step" :class="{ complete: zepReady }" @click="setTab('zep')"><span class="step-number"><Icon v-if="zepReady" name="check" /><template v-else>02</template></span><span><strong>连接 Zep 记忆</strong><small>{{ zepReady ? status.zep?.active_name || activeZep.name : '配置连接和备用密钥' }}</small></span><Icon name="chevron" /></button>
                <button class="setup-step" :class="{ complete: engineReady }" :disabled="!!action || !connected" @click="engineReady ? openNew() : engineAction('start')"><span class="step-number"><Icon v-if="engineReady" name="check" /><template v-else>03</template></span><span><strong>{{ engineReady ? '创建新的推演' : '启动推演引擎' }}</strong><small>{{ engineReady ? canCreate ? '从一份材料、一个问题开始' : '完成上面的配置后即可开始' : '启动后即可进入推演流程' }}</small></span><Icon :name="action === 'engine-start' ? 'loader' : 'arrow'" :class="{ spinning: action === 'engine-start' }" /></button>
              </div>
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
            <section class="surface recent-card"><div class="section-title"><h2>最近的推演</h2><button class="text-button" @click="setTab('records')">全部记录<Icon name="arrow" /></button></div><div v-if="recordsLoading" class="empty-state compact"><Icon class="spinning" name="loader" /><p>正在读取记录…</p></div><div v-else-if="recordsError" class="empty-state compact"><Icon name="info" /><p>{{ recordsError }}</p><button class="text-button" @click="loadRecords">重试</button></div><div v-else-if="!recentProjects.length" class="empty-state compact"><span class="empty-icon"><Icon name="folder" /></span><h3>还没有推演项目</h3><p>创建推演后，最近的项目会出现在这里。</p><button class="text-button" :disabled="!canCreate" @click="openNew">创建第一条推演<Icon name="arrow" /></button></div><div v-else class="recent-list"><button v-for="project in recentProjects" :key="project.project_id" class="recent-row" :disabled="!engineReady" @click="openRecord(project)"><span class="record-icon"><Icon :name="project.report_id ? 'file' : 'folder'" /></span><span class="recent-main"><strong>{{ project.name || '未命名推演' }}</strong><small>{{ formatDate(project.created_at) }}</small></span><span class="badge badge-neutral">{{ recordStatus(project.report_status || project.simulation_status || project.status) }}</span><Icon name="chevron" /></button></div><p v-if="recentProjects.length && !engineReady" class="card-bottom-note">启动引擎后，即可打开已有项目。</p></section>
            <section class="surface current-card"><div class="section-title"><h2>当前配置</h2><span class="quiet-label">新任务使用</span></div><button class="current-config" @click="setTab('models')"><span class="config-icon"><Icon name="cpu" /></span><span><small>AI 模型</small><strong>{{ activeModel?.name || '尚未选择模型预设' }}</strong><em>{{ activeModel?.model || '添加并设为当前，即可使用' }}</em></span><Icon name="chevron" /></button><button class="current-config" @click="setTab('zep')"><span class="config-icon"><Icon name="link" /></span><span><small>Zep 记忆连接</small><strong>{{ status.zep?.active_name || activeZep?.name || '尚未配置 Zep' }}</strong><em>{{ config.auto_zep ? '自动切换已开启' : '自动切换已关闭' }} · {{ config.zep.length }} 个已存连接</em></span><Icon name="chevron" /></button><div class="local-note"><Icon name="shield" /><p>密钥由本机加密保存；调用时发送给你配置的服务。</p></div></section>
          </div>
          <details class="logs-panel" @toggle="onLogsToggle"><summary><span><Icon name="activity" />运行日志</span><span>遇到问题时查看<Icon name="chevron" /></span></summary><div class="logs-toolbar"><span>最近的运行信息</span><button class="text-button" :disabled="logsLoading" @click="loadLogs"><Icon name="refresh" :class="{ spinning: logsLoading }" />刷新</button></div><pre class="log-output">{{ logsLoading && !logs.length ? '正在读取日志…' : logsError || logs.join('\n') || '暂无运行日志。' }}</pre></details>
        </template>

        <template v-else-if="tab === 'models'">
          <section class="page-heading"><div><h1>模型预设</h1><p class="page-description">保存服务地址与模型，按任务切换正在使用的预设。</p></div><button class="button button-primary" :disabled="!!action" @click="newModel"><Icon name="plus" />添加模型预设</button></section>
          <div v-if="status.busy" class="alert alert-info"><Icon name="info" /><p>当前有任务进行中。你可以保存新预设，任务结束后再切换正在使用的配置。</p></div>
          <div class="config-layout">
            <section class="config-list-section" aria-labelledby="models-title"><div class="list-heading"><h2 id="models-title">已保存的预设 <span>{{ config.models.length }}</span></h2><span class="quiet-label">保存后随时使用</span></div>
              <div v-if="initialLoading" class="surface empty-state"><Icon class="spinning" name="loader" /><p>正在读取预设…</p></div>
              <div v-else-if="!config.models.length" class="surface empty-state tall-empty"><span class="empty-icon"><Icon name="cpu" /></span><h3>添加你的第一个模型</h3><p>填入服务地址与 API Key，获取模型列表，<br>保存为你的第一套预设。</p><div class="empty-tip"><Icon name="arrow" />从右侧表单开始</div></div>
              <article v-for="model in config.models" :key="model.id" class="surface preset-card" :class="{ selected: model.id === config.active_model_id, editing: model.id === modelForm.id }"><div class="preset-top"><span class="preset-icon"><Icon name="cpu" /></span><div class="preset-title"><h3>{{ model.name }}</h3><span>{{ endpointLabel(model.base_url) }}</span></div><span v-if="model.id === config.active_model_id" class="badge badge-green"><Icon name="check" />当前使用</span></div><div class="model-name">{{ model.model || '尚未设置模型' }}</div><div class="preset-details"><span><span class="status-dot" :class="model.has_key ? 'good' : 'muted'"></span>{{ model.has_key ? `密钥已保存${model.key_hint ? ' · ' + model.key_hint : ''}` : '尚未保存密钥' }}</span><span v-if="model.enabled === false">已停用</span></div><div class="preset-actions"><button class="button button-small" :class="model.id === config.active_model_id ? 'button-soft' : 'button-primary'" :disabled="!!action || model.id === config.active_model_id || !modelHasCredentials(model) || !model.model || model.enabled === false || status.busy" @click="activateModel(model)"><Icon v-if="action === `activate-model-${model.id}`" class="spinning" name="loader" /><Icon v-else :name="model.id === config.active_model_id ? 'check' : 'play'" />{{ model.id === config.active_model_id ? '正在使用' : action === `activate-model-${model.id}` ? '切换中…' : '设为当前' }}</button><div><button class="icon-button" :disabled="!!action" :aria-label="`编辑 ${model.name}`" title="编辑预设" @click="editModel(model)"><Icon name="edit" /></button><button class="icon-button danger-icon" :disabled="!!action || status.busy" :aria-label="`删除 ${model.name}`" title="删除预设" @click="deleteModel(model)"><Icon name="trash" /></button></div></div></article>
              <p class="section-footnote"><Icon name="info" />启用后用于新任务。已有采访环境保留原配置；任务进行中请在完成后切换。</p>
            </section>

            <section class="surface editor-panel" aria-labelledby="model-editor-title"><div class="editor-title"><div><span class="section-kicker">{{ modelForm.id ? 'EDIT PRESET' : 'NEW PRESET' }}</span><h2 id="model-editor-title">{{ modelForm.id ? '编辑模型预设' : '添加模型预设' }}</h2></div><button v-if="modelForm.id" class="text-button" :disabled="!!action" @click="newModel">新建</button></div>
              <form @submit.prevent="saveModel"><fieldset :disabled="!!action"><div v-if="config.presets.length" class="form-field"><label for="model-provider">快速填入服务地址 <span class="optional">可选</span></label><select id="model-provider" v-model="quickPreset" @change="applyQuickPreset"><option value="">自定义 / 选择服务商</option><option v-for="(preset, index) in config.presets" :key="preset.name" :value="String(index)">{{ preset.name }}</option></select></div>
                <div class="form-field"><label for="model-name">预设名称</label><input id="model-name" ref="modelNameInput" v-model.trim="modelForm.name" required maxlength="80" placeholder="例如：日常推演 · 快速模型" autocomplete="off" /></div>
                <div class="form-field"><label for="model-base-url">服务地址 <span class="field-en">Base URL</span></label><input id="model-base-url" v-model.trim="modelForm.base_url" type="url" required placeholder="https://api.example.com/v1" spellcheck="false" autocomplete="off" aria-describedby="base-url-help" /><p id="base-url-help" class="field-help">填写兼容 OpenAI 的完整接口基础地址。</p></div>
                <div class="form-field"><label for="model-key">API Key <span v-if="editingModel?.has_key" class="saved-label">已保存</span></label><div class="input-with-button"><input id="model-key" v-model.trim="modelForm.key" :type="showModelKey ? 'text' : 'password'" :required="!editingModel?.has_key && !isLocalEndpoint(modelForm.base_url)" :placeholder="editingModel?.has_key ? '留空保留已保存的密钥' : '粘贴你的 API Key'" autocomplete="off" spellcheck="false" /><button class="icon-button" type="button" :aria-label="showModelKey ? '隐藏模型密钥' : '显示模型密钥'" :aria-pressed="showModelKey" @click="showModelKey = !showModelKey"><Icon :name="showModelKey ? 'eye-off' : 'eye'" /></button></div></div>
                <div class="form-field"><div class="field-label-row"><label for="model-id">模型名称</label><button class="text-button" type="button" :disabled="!modelForm.base_url || (!modelForm.key && !editingModel?.has_key && !isLocalEndpoint(modelForm.base_url))" @click="discoverModels"><Icon :name="action === 'discover-models' ? 'loader' : 'refresh'" :class="{ spinning: action === 'discover-models' }" />{{ action === 'discover-models' ? '正在获取…' : '获取模型' }}</button></div><input id="model-id" v-model.trim="modelForm.model" list="studio-model-options" required placeholder="获取后选择，或手动输入模型名称" autocomplete="off" spellcheck="false" /><datalist id="studio-model-options"><option v-for="name in discoveredModels" :key="name" :value="name" /></datalist><p class="field-help">{{ discoveredModels.length ? `已获取 ${discoveredModels.length} 个模型，点击输入框选择，也可输入关键字。` : '有些服务不提供模型列表，可以直接填写准确名称。' }}</p></div>
              </fieldset><Transition name="feedback" mode="out-in"><div v-if="modelFeedback" :key="modelFeedback.message" class="form-feedback" :class="modelFeedback.type" :role="modelFeedback.type === 'error' ? 'alert' : 'status'"><Icon :name="modelFeedback.type === 'error' ? 'info' : 'check'" /><span>{{ modelFeedback.message }}</span></div></Transition><div class="form-actions"><button class="button button-outline" type="button" :disabled="!!action || !connected" @click="testModel"><Icon :name="action === 'test-model' ? 'loader' : 'activity'" :class="{ spinning: action === 'test-model' }" />{{ action === 'test-model' ? '测试中…' : '测试连接' }}</button><button class="button button-primary" type="submit" :disabled="!!action || !connected"><Icon :name="action === 'save-model' ? 'loader' : 'check'" :class="{ spinning: action === 'save-model' }" />{{ action === 'save-model' ? '保存中…' : '保存预设' }}</button></div><p class="form-footer">{{ modelForm.id && modelForm.id === config.active_model_id ? '当前预设保存后，将直接用于新任务。' : '保存后，在预设卡片点击「设为当前」即可切换。' }}</p></form>
            </section>
          </div>
        </template>

        <template v-else-if="tab === 'zep'">
          <section class="page-heading"><div><h1>Zep 连接</h1><p class="page-description">统一保存 Zep 密钥，为同一项目配置备用连接。</p></div><button class="button button-primary" :disabled="!!action" @click="newZep"><Icon name="plus" />添加 Zep 连接</button></section>
          <section class="surface rotation-card"><div class="rotation-icon"><Icon name="refresh" /></div><div class="rotation-copy"><div><h2>自动切换可用密钥</h2><span class="badge" :class="config.auto_zep ? 'badge-green' : 'badge-neutral'">{{ config.auto_zep ? '已开启' : '已关闭' }}</span></div><p>当前连接不可用时，尝试同组的其他可用密钥，减少手动处理。</p></div><button class="switch" role="switch" :aria-checked="config.auto_zep" aria-label="自动切换 Zep 可用密钥" :class="{ on: config.auto_zep }" :disabled="!!action || !connected" @click="toggleRotation"><span></span></button></section>
          <div class="config-layout"><section class="config-list-section" aria-labelledby="zep-list-title"><div class="list-heading"><h2 id="zep-list-title">已保存的连接 <span>{{ config.zep.length }}</span></h2><span class="quiet-label">{{ status.zep?.available ?? config.zep.filter(item => item.enabled !== false && item.has_key).length }} 个已启用</span></div><div v-if="initialLoading" class="surface empty-state"><Icon class="spinning" name="loader" /><p>正在读取连接…</p></div><div v-else-if="!config.zep.length" class="surface empty-state tall-empty"><span class="empty-icon"><Icon name="link" /></span><h3>为推演连接长期记忆</h3><p>保存第一条 Zep 连接，再添加同一项目的<br>备用密钥，组成可自动切换的连接组。</p><div class="empty-tip"><Icon name="arrow" />从右侧表单开始</div></div>
              <article v-for="connection in config.zep" :key="connection.id" class="surface preset-card zep-card" :class="{ selected: connection.id === config.active_zep_id, editing: connection.id === zepForm.id }"><div class="preset-top"><span class="preset-icon"><Icon name="link" /></span><div class="preset-title"><h3>{{ connection.name }}</h3><span>连接组 · {{ connection.group || '独立连接' }}</span></div><span v-if="connection.id === config.active_zep_id" class="badge badge-green"><Icon name="check" />当前使用</span><span v-else-if="connection.enabled === false" class="badge badge-neutral">已停用</span><span v-else class="badge badge-neutral">备用连接</span></div><div class="key-summary"><Icon name="shield" /><span>{{ connection.has_key ? connection.key_hint || '密钥已安全保存' : '尚未保存密钥' }}</span></div><div class="preset-actions"><button class="button button-small" :class="connection.id === config.active_zep_id ? 'button-soft' : 'button-primary'" :disabled="!!action || connection.id === config.active_zep_id || !connection.has_key || connection.enabled === false || status.busy" @click="activateZep(connection)"><Icon :name="action === `activate-zep-${connection.id}` ? 'loader' : connection.id === config.active_zep_id ? 'check' : 'play'" :class="{ spinning: action === `activate-zep-${connection.id}` }" />{{ connection.id === config.active_zep_id ? '正在使用' : action === `activate-zep-${connection.id}` ? '切换中…' : '设为当前' }}</button><div><button class="icon-button" :disabled="!!action" :aria-label="`编辑 ${connection.name}`" title="编辑连接" @click="editZep(connection)"><Icon name="edit" /></button><button class="icon-button danger-icon" :disabled="!!action || status.busy" :aria-label="`删除 ${connection.name}`" title="删除连接" @click="deleteZep(connection)"><Icon name="trash" /></button></div></div></article>
              <div class="group-explainer"><Icon name="info" /><div><strong>同一个项目，放在同一个连接组</strong><p>备用密钥必须能访问相同的 Zep 项目和图谱。不同账号或项目的密钥，请使用不同组名；它们不能接替已有图谱的连接。</p></div></div>
            </section>
            <section class="surface editor-panel" aria-labelledby="zep-editor-title"><div class="editor-title"><div><span class="section-kicker">{{ zepForm.id ? 'EDIT CONNECTION' : 'NEW CONNECTION' }}</span><h2 id="zep-editor-title">{{ zepForm.id ? '编辑 Zep 连接' : '添加 Zep 连接' }}</h2></div><button v-if="zepForm.id" class="text-button" :disabled="!!action" @click="newZep">新建</button></div><form @submit.prevent="saveZep"><fieldset :disabled="!!action"><div class="form-field"><label for="zep-name">连接名称</label><input id="zep-name" ref="zepNameInput" v-model.trim="zepForm.name" required maxlength="80" placeholder="例如：主项目 · 备用连接" autocomplete="off" /></div><div class="form-field"><label for="zep-group">连接组</label><input id="zep-group" v-model.trim="zepForm.group" maxlength="80" list="studio-zep-groups" placeholder="例如：我的主项目" autocomplete="off" aria-describedby="zep-group-help" /><datalist id="studio-zep-groups"><option v-for="group in zepGroups" :key="group" :value="group" /></datalist><p id="zep-group-help" class="field-help">可留空作为独立账号。能访问同一图谱的密钥填写同一组名，才会在已有推演中互为备用。</p></div><div class="form-field"><label for="zep-key">Zep API Key <span v-if="editingZep?.has_key" class="saved-label">已保存</span></label><div class="input-with-button"><input id="zep-key" v-model.trim="zepForm.key" :type="showZepKey ? 'text' : 'password'" :required="!editingZep?.has_key" :placeholder="editingZep?.has_key ? '留空保留已保存的密钥' : '粘贴你的 Zep API Key'" autocomplete="off" spellcheck="false" /><button class="icon-button" type="button" :aria-label="showZepKey ? '隐藏 Zep 密钥' : '显示 Zep 密钥'" :aria-pressed="showZepKey" @click="showZepKey = !showZepKey"><Icon :name="showZepKey ? 'eye-off' : 'eye'" /></button></div></div><label class="checkbox-label"><input v-model="zepForm.enabled" type="checkbox" /><span>启用此连接<small>停用后不参与自动切换</small></span></label></fieldset><Transition name="feedback" mode="out-in"><div v-if="zepFeedback" :key="zepFeedback.message" class="form-feedback" :class="zepFeedback.type" :role="zepFeedback.type === 'error' ? 'alert' : 'status'"><Icon :name="zepFeedback.type === 'error' ? 'info' : 'check'" /><span>{{ zepFeedback.message }}</span></div></Transition><div class="form-actions"><button class="button button-outline" type="button" :disabled="!!action || !connected" @click="testZep"><Icon :name="action === 'test-zep' ? 'loader' : 'activity'" :class="{ spinning: action === 'test-zep' }" />{{ action === 'test-zep' ? '测试中…' : '测试连接' }}</button><button class="button button-primary" type="submit" :disabled="!!action || !connected"><Icon :name="action === 'save-zep' ? 'loader' : 'check'" :class="{ spinning: action === 'save-zep' }" />{{ action === 'save-zep' ? '保存中…' : '保存连接' }}</button></div><p class="form-footer">连接信息保存在本机，已有密钥不会回显。</p></form></section>
          </div>
        </template>

        <template v-else-if="tab === 'records'">
          <section class="page-heading"><div><h1>记录与备份</h1><p class="page-description">查看本机推演，创建记录备份，在需要时恢复。</p></div><button class="button button-primary" :disabled="!!action || !connected" @click="createBackup"><Icon :name="action === 'create-backup' ? 'loader' : 'archive'" :class="{ spinning: action === 'create-backup' }" />{{ action === 'create-backup' ? '正在备份…' : '立即备份记录' }}</button></section>
          <section class="surface records-panel"><div class="section-title"><h2>推演记录 <span class="count-label">{{ records.projects.length }}</span></h2><div class="search-field"><Icon name="search" /><input v-model="recordQuery" type="search" aria-label="搜索推演记录" placeholder="搜索推演名称" /></div></div><div v-if="recordsLoading && !records.projects.length" class="empty-state"><Icon class="spinning" name="loader" /><p>正在读取推演记录…</p></div><div v-else-if="recordsError" class="empty-state"><Icon name="info" /><p>{{ recordsError }}</p><button class="button button-soft" @click="loadRecords">重新读取</button></div><div v-else-if="!filteredProjects.length" class="empty-state"><span class="empty-icon"><Icon :name="recordQuery ? 'search' : 'folder'" /></span><h3>{{ recordQuery ? '没有匹配的推演' : '这里还没有推演记录' }}</h3><p>{{ recordQuery ? '换一个关键词试试。' : '新建推演后，项目与报告会在这里集中管理。' }}</p></div><div v-else class="table-scroll"><table class="records-table"><thead><tr><th scope="col">项目</th><th scope="col">创建时间</th><th scope="col">进度</th><th scope="col"><span class="sr-only">操作</span></th></tr></thead><tbody><tr v-for="project in filteredProjects" :key="project.project_id"><td><div class="table-project"><span class="record-icon"><Icon :name="project.report_id ? 'file' : 'folder'" /></span><div><strong>{{ project.name || '未命名推演' }}</strong><small>{{ project.report_id ? '已关联报告' : project.simulation_id ? '已关联推演' : '项目材料' }}</small></div></div></td><td>{{ formatDate(project.created_at) }}</td><td><span class="badge badge-neutral">{{ recordStatus(project.report_status || project.simulation_status || project.status) }}</span></td><td><button class="text-button" :disabled="!engineReady" @click="openRecord(project)">{{ project.report_id ? '查看报告' : '继续查看' }}<Icon name="arrow" /></button></td></tr></tbody></table></div><p v-if="records.projects.length && !engineReady" class="card-bottom-note">请先在工作台启动引擎，再打开已有项目。</p></section>
          <section class="surface backups-panel"><div class="section-title"><div><h2>记录备份 <span class="count-label">{{ backups.length }}</span></h2><p class="section-subtitle">备份包含推演记录，不包含 API Key。</p></div><button class="text-button" :disabled="backupsLoading" @click="loadBackups"><Icon name="refresh" :class="{ spinning: backupsLoading }" />刷新</button></div><div v-if="backupsLoading && !backups.length" class="empty-state compact"><Icon class="spinning" name="loader" /><p>正在读取备份…</p></div><div v-else-if="backupsError" class="empty-state compact"><Icon name="info" /><p>{{ backupsError }}</p><button class="text-button" @click="loadBackups">重试</button></div><div v-else-if="!backups.length" class="empty-state compact"><span class="empty-icon"><Icon name="archive" /></span><h3>还没有记录备份</h3><p>点击「立即备份记录」，在本机保存当前记录。</p></div><div v-else class="backup-list"><div v-for="backup in backups" :key="backup.name" class="backup-row"><span class="backup-file-icon"><Icon name="archive" /></span><div class="backup-details"><strong :title="backup.name">{{ backup.name }}</strong><small>{{ formatDate(backup.created_at) }} <span>·</span> {{ formatSize(backup.size) }}<template v-if="backup.file_count != null"> <span>·</span> {{ backup.file_count }} 个文件</template></small></div><button class="button button-small button-outline" :disabled="!!action || !connected || status.engine?.state !== 'stopped'" :title="status.engine?.state !== 'stopped' ? '停止引擎后可以恢复记录' : '恢复此备份'" @click="restoreBackup(backup)"><Icon :name="action === `restore-${backup.name}` ? 'loader' : 'refresh'" :class="{ spinning: action === `restore-${backup.name}` }" />{{ action === `restore-${backup.name}` ? '恢复中…' : '恢复' }}</button></div></div><div class="backup-guidance"><Icon name="info" /><div><p>恢复需要先停止推演引擎；恢复前会为当前数据创建回退备份。</p><p>有记录变化时每 15 分钟自动备份，保留最近 20 份自动备份。页面断线可继续查看；程序中断不会自动从中间轮次续跑。</p><p v-if="status.paths?.backups" class="path-note">备份位置 <code>{{ status.paths.backups }}</code></p></div></div></section>
        </template>

        </div>
        </Transition>

        <footer class="workspace-footer"><span>MiroFish Studio</span><span>配置与记录保存在本机</span><span class="footer-local"><span class="status-dot" :class="connected ? 'good' : 'muted'"></span> 本地工作空间</span></footer>
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
    if (window.mirofishDesktop) await window.mirofishDesktop.quit()
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
/* Shared desktop tokens: stable surfaces, readable type and short feedback. */
.studio-shell {
  --canvas:#f4f7fb; --surface:#fff; --sidebar:#111c2e; --ink:#1c2a3d;
  --muted:#627187; --line:#e0e7ef; --line-strong:#c6d2df; --soft:#eaf6f2;
  --primary:#0d8a70; --primary-hover:#08725c; --success:#086e57; --danger:#b83b45;
  --radius:14px; --ease:cubic-bezier(.2,.7,.2,1); --motion:180ms; --shadow:0 2px 6px rgb(20 39 64 / 3%);
  display:flex; min-height:100vh; color:var(--ink); background:var(--canvas);
  font:14px/1.55 "Segoe UI","Microsoft YaHei",-apple-system,BlinkMacSystemFont,sans-serif; -webkit-font-smoothing:antialiased;
}
.studio-shell *, .studio-shell *::before, .studio-shell *::after { box-sizing:border-box; }
.studio-shell :where(button,input,select) { font:inherit; }
.studio-shell :is(button,a) { touch-action:manipulation; }
.studio-shell button { cursor:pointer; }
.studio-shell button:disabled { cursor:not-allowed; box-shadow:none; }
.studio-shell :is(button,a,input,select,summary) { -webkit-tap-highlight-color:transparent; }
.studio-shell :is(button,a,input,select,summary):focus-visible { outline:3px solid #28a58a; outline-offset:3px; }
.studio-shell :is(h1,h2,h3,p) { margin:0; }
.studio-shell h2 { font-size:16px; font-weight:650; line-height:1.5; }
.studio-shell h3 { font-size:15px; font-weight:650; }
.skip-link { position:fixed; z-index:50; top:-80px; left:24px; padding:12px 18px; border-radius:8px; background:var(--surface); color:var(--primary); box-shadow:0 6px 24px #14274030; }
.skip-link:focus { top:14px; }

/* Sidebar and toolbar stay still when the content pane changes. */
.studio-sidebar { position:fixed; inset:0 auto 0 0; z-index:20; width:224px; display:flex; flex-direction:column; padding:28px 16px 20px; background:var(--sidebar); color:#edf3fa; border-right:1px solid #1c2a3f; }
.studio-brand { display:flex; align-items:center; gap:11px; padding:0 8px; color:inherit; text-decoration:none; width:fit-content; border-radius:10px; }
.brand-symbol { display:grid; place-items:center; width:38px; height:38px; border:1px solid #365464; border-radius:11px; background:#203c47; color:#90e0c8; transition:transform 220ms var(--ease),background var(--motion); }
.brand-symbol .studio-icon { width:27px; height:27px; stroke-width:1.6; }
.studio-brand:hover .brand-symbol { transform:rotate(-7deg); background:#284c55; }
.brand-type { font-size:20px; font-weight:650; letter-spacing:-.4px; line-height:1.15; }
.brand-type > span { display:flex; align-items:center; gap:8px; margin-top:6px; color:#a4b5cb; font-size:10px; letter-spacing:2.5px; font-weight:600; }
.brand-type i { font-style:normal; letter-spacing:.2px; color:#bdcce0; font-size:10px; }
.sidebar-label { margin:38px 14px 12px; color:#8495ad; font-size:12px; letter-spacing:1px; }
.studio-nav { display:grid; gap:7px; }
.studio-nav button { position:relative; display:flex; align-items:center; gap:12px; width:100%; min-height:46px; padding:0 14px; border:1px solid transparent; border-radius:9px; background:transparent; color:#b5c3d6; text-align:left; transition:color var(--motion),background var(--motion),border-color var(--motion),transform var(--motion) var(--ease); }
.studio-nav button::before { position:absolute; content:""; left:-1px; top:13px; bottom:13px; width:3px; border-radius:0 3px 3px 0; background:#6edabc; opacity:0; transform:scaleY(.3); transition:opacity 200ms,transform 200ms var(--ease); }
.studio-nav button:hover { color:#f3f8ff; background:#1c2b42; transform:translateX(2px); }
.studio-nav button:active { transform:translateX(1px); background:#24354c; }
.studio-nav button.active { color:#c1f5e8; background:#173a3e; border-color:#285054; font-weight:600; }
.studio-nav button.active::before { opacity:1; transform:scaleY(1); }
.studio-nav button.active > .studio-icon:first-child { color:#76dabb; }
.studio-nav button > .studio-icon { width:19px; height:19px; }
.studio-nav .nav-arrow { margin-left:auto; width:14px; height:14px; color:#85cbb8; }
.sidebar-bottom { margin-top:auto; padding:28px 6px 0; }
.quit-studio { display:flex; align-items:center; gap:10px; width:100%; min-height:42px; margin-bottom:22px; padding:9px 12px; border:1px solid #334159; border-radius:8px; background:transparent; color:#bfcede; font-size:13px; transition:background var(--motion),color var(--motion),border-color var(--motion); }
.quit-studio .studio-icon { width:17px; height:17px; }
.quit-studio:hover:not(:disabled) { background:#2a2537; border-color:#685162; color:#ffd7dd; }
.quit-studio:active:not(:disabled) { background:#382b40; }
.quit-studio:disabled { color:#8290a5; border-color:#2a354a; background:#172237; }
.sidebar-note { display:flex; align-items:center; gap:10px; padding:0 6px 20px; color:#c0cde0; font-size:12px; }
.sidebar-note > .studio-icon { width:19px; height:19px; color:#8faac1; }
.sidebar-note small { display:block; margin-top:3px; color:#92a4bc; font-size:12px; }
.studio-connection { display:flex; align-items:center; gap:8px; padding:16px 4px 0; border-top:1px solid #2a364c; color:#a9bad0; font-size:12px; }
.studio-main { flex:1; min-width:0; margin-left:224px; }
.topbar { position:sticky; top:0; z-index:10; min-height:64px; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:0 32px; border-bottom:1px solid var(--line); background:#fffffff5; }
.breadcrumb { display:flex; align-items:center; gap:12px; font-size:13px; color:var(--muted); }
.breadcrumb > span { color:#a8b5c5; }
.breadcrumb strong { color:var(--ink); font-weight:600; }
.topbar-actions { display:flex; align-items:center; gap:14px; }
.topbar-status { display:inline-flex; align-items:center; gap:7px; font-size:12px; color:var(--muted); }
.version-pill { padding:3px 7px; background:#f0f4f8; border:1px solid var(--line); border-radius:5px; font-size:11px; color:#65738a; font-variant-numeric:tabular-nums; }
.workspace { display:flex; flex-direction:column; min-height:calc(100vh - 64px); max-width:1540px; margin:0 auto; padding:28px 32px 20px; }
.tab-pane { flex:1; min-width:0; }
.page-heading { display:flex; align-items:center; justify-content:space-between; gap:24px; margin-bottom:24px; }
.page-heading h1 { font-size:27px; line-height:1.35; font-weight:650; letter-spacing:-.6px; }
.page-description { margin-top:7px !important; color:var(--muted); font-size:14px; line-height:1.6; }

/* Consistent buttons, labels and visible interaction states. */
.button { display:inline-flex; align-items:center; justify-content:center; gap:8px; min-height:42px; padding:10px 16px; border:1px solid transparent; border-radius:8px; font-size:13px; font-weight:600; line-height:1.4; white-space:nowrap; text-decoration:none; transition:transform var(--motion) var(--ease),background var(--motion),border-color var(--motion),box-shadow var(--motion),color var(--motion); }
.button .studio-icon { width:17px; height:17px; }
.button-primary { background:var(--primary); border-color:var(--primary); color:#fff; box-shadow:0 3px 7px #0d8a701a; }
.button-primary:hover:not(:disabled) { background:var(--primary-hover); border-color:var(--primary-hover); box-shadow:0 5px 12px #0d8a7030; transform:translateY(-1px); }
.button-soft { background:var(--soft); border-color:#d0e8df; color:var(--success); }
.button-soft:hover:not(:disabled) { background:#dcefe8; border-color:#abd3c6; transform:translateY(-1px); }
.button-outline { background:var(--surface); border-color:var(--line-strong); color:#40516a; }
.button-outline:hover:not(:disabled) { background:#f7fafc; border-color:#8eaaa5; box-shadow:0 3px 9px #20374a0b; transform:translateY(-1px); }
.button:active:not(:disabled) { transform:translateY(0) scale(.985); box-shadow:none; transition-duration:80ms; }
.button:disabled { background:#eef1f5; color:#7d899a; border-color:#dfe5ec; }
.button-small { min-height:36px; padding:8px 12px; font-size:12px; }
.icon-button { display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; width:36px; height:36px; padding:0; border:1px solid transparent; border-radius:8px; color:var(--muted); background:transparent; transition:transform var(--motion) var(--ease),background var(--motion),color var(--motion),border-color var(--motion); }
.icon-button .studio-icon { width:17px; height:17px; transition:transform var(--motion) var(--ease); }
.icon-button:hover:not(:disabled) { border-color:#cde4dd; background:var(--soft); color:var(--primary-hover); }
.icon-button:hover:not(:disabled) .studio-icon:not(.spinning) { transform:scale(1.08); }
.icon-button:active:not(:disabled) { transform:scale(.93); transition-duration:80ms; }
.icon-button:disabled { color:#9aa5b3; }
.danger-icon:hover:not(:disabled) { border-color:#efd3d7; background:#fff0f2; color:var(--danger); }
.text-button { display:inline-flex; align-items:center; justify-content:center; gap:7px; min-height:34px; padding:5px 7px; border:1px solid transparent; border-radius:6px; background:transparent; color:var(--primary-hover); font-size:13px; font-weight:600; white-space:nowrap; transition:background var(--motion),color var(--motion),transform var(--motion) var(--ease); }
.text-button:hover:not(:disabled) { background:var(--soft); color:var(--success); }
.text-button:active:not(:disabled) { transform:scale(.97); background:#dceee7; }
.text-button:disabled { color:#8290a3; }
.text-button .studio-icon { width:15px; height:15px; }
:is(.text-button,.button,.setup-step,.recent-row,.current-config) > .studio-icon:last-child { transition:transform var(--motion) var(--ease); }
:is(.text-button,.button):hover:not(:disabled) > .studio-icon:last-child:not(:first-child):not(.spinning),
:is(.setup-step,.recent-row,.current-config):hover:not(:disabled) > .studio-icon:last-child:not(.spinning) { transform:translateX(3px); }
.surface { background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); box-shadow:var(--shadow); }
.section-title { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.section-kicker { color:var(--muted); font-size:12px; font-weight:600; letter-spacing:.3px; }
.quiet-label { color:var(--muted); font-size:12px; white-space:nowrap; }
.badge { display:inline-flex; align-items:center; justify-content:center; flex-shrink:0; gap:5px; padding:3px 7px; border:1px solid transparent; border-radius:5px; font-size:12px; font-weight:500; line-height:1.5; white-space:nowrap; }
.badge .studio-icon { width:13px; height:13px; }
.badge-green { color:var(--success); background:#e5f5ee; border-color:#c9e7da; }
.badge-neutral { color:#627188; background:#f1f4f8; border-color:#e2e8f0; }
.badge-red { color:#a33240; background:#fff0f2; border-color:#f2d3d9; }
.status-dot { display:inline-block; flex-shrink:0; width:6px; height:6px; border-radius:50%; background:#929fb0; }
.status-dot.good { background:#159c7a; box-shadow:0 0 0 3px #159c7a10; }
.status-dot.muted { background:#8d9aab; }

/* Dashboard uses compact status panels instead of a promotional hero. */
.dashboard-top { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(290px,1fr); gap:20px; }
.launch-card { min-width:0; padding:22px 24px 14px; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); box-shadow:var(--shadow); }
.launch-copy { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.launch-copy h2 { margin:4px 0 6px; font-size:20px; font-weight:650; letter-spacing:-.3px; }
.launch-copy p { color:var(--muted); font-size:13px; }
.setup-summary { display:flex; flex-direction:column; align-items:center; justify-content:center; flex-shrink:0; min-width:68px; min-height:68px; padding:9px 12px; border-radius:12px; background:#f1f5f9; border:1px solid #e4eaf1; }
.setup-summary strong { color:#51657f; font-size:25px; font-weight:600; line-height:1.1; font-variant-numeric:tabular-nums; }
.setup-summary strong small { margin-left:3px; font-size:13px; font-weight:500; color:var(--muted); }
.setup-summary > span { margin-top:5px; color:var(--muted); font-size:11px; }
.setup-summary.ready { background:var(--soft); border-color:#cde7dd; }
.setup-summary.ready strong { color:var(--primary); }
.setup-steps { display:grid; gap:5px; margin-top:19px; }
.setup-step { display:flex; align-items:center; gap:12px; width:100%; min-height:59px; padding:10px 12px; border:1px solid transparent; border-radius:9px; background:#f7f9fc; color:var(--ink); text-align:left; transition:background var(--motion),border-color var(--motion),transform var(--motion) var(--ease); }
.setup-step > span:nth-child(2) { min-width:0; flex:1; }
.setup-step:hover:not(:disabled) { background:#eef7f4; border-color:#cce3da; transform:translateX(2px); }
.setup-step:active:not(:disabled) { transform:translateX(0); background:#e1f0e9; }
.setup-step:disabled { color:#7c899b; background:#f1f4f7; }
.step-number { display:grid; place-items:center; flex-shrink:0; width:28px; height:28px; border:1px solid #dce4ed; border-radius:8px; background:#fff; color:#758399; font-size:11px; font-weight:600; font-variant-numeric:tabular-nums; }
.step-number .studio-icon { width:15px; height:15px; }
.setup-step.complete .step-number { color:var(--success); background:#e0f2eb; border-color:#c7e6da; }
.setup-step strong { display:block; font-size:13px; font-weight:600; }
.setup-step small { display:block; margin-top:2px; color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.setup-step > .studio-icon:last-child { width:15px; height:15px; color:#73879b; }
.engine-card { display:flex; flex-direction:column; min-width:0; padding:22px 24px 18px; }
.engine-visual { display:flex; align-items:center; gap:12px; margin:26px 0 13px; font-size:20px; font-weight:600; letter-spacing:-.4px; }
.engine-visual .studio-icon { width:46px; height:46px; padding:12px; border-radius:12px; background:#f0f3f8; color:#74859b; }
.engine-visual.ready .studio-icon { background:#e6f5ef; color:var(--primary); }
.engine-message { min-height:42px; color:var(--muted); font-size:13px; line-height:1.75; overflow-wrap:anywhere; }
.inline-info { display:flex; align-items:flex-start; gap:7px; margin-top:8px; padding:8px 10px; background:#f1f6fa; border-radius:7px; color:#547088; font-size:12px; }
.inline-info .studio-icon { width:15px; height:15px; margin-top:2px; }
.engine-controls { display:flex; gap:10px; margin-top:18px; }
.engine-controls > .button { flex:1; }
.engine-foot { display:flex; justify-content:space-between; flex-wrap:wrap; gap:7px; margin-top:auto; padding-top:23px; color:var(--muted); font-size:11px; }

.stat-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; margin-top:20px; }
.stat-card { display:flex; align-items:center; gap:14px; padding:18px 20px; }
.stat-icon { display:grid; place-items:center; flex-shrink:0; width:40px; height:40px; border-radius:10px; background:#edf2f8; color:#607797; }
.stat-icon .studio-icon { width:20px; height:20px; }
.stat-label { display:block; color:var(--muted); font-size:12px; }
.stat-card strong { display:block; margin-top:3px; font-size:27px; line-height:1.2; font-weight:600; letter-spacing:-.5px; font-variant-numeric:tabular-nums; }
.stat-caption { margin-left:auto; color:#748399; font-size:11px; white-space:nowrap; }
.dashboard-bottom { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(0,1fr); gap:20px; margin-top:20px; }
.recent-card, .current-card { min-width:0; padding:20px 22px; }
.recent-card > .section-title, .current-card > .section-title { margin-bottom:12px; }
.recent-row { display:flex; align-items:center; gap:12px; width:100%; min-height:72px; padding:12px 8px; border:1px solid transparent; border-bottom-color:#edf1f6; border-radius:8px; text-align:left; background:transparent; color:var(--ink); transition:background var(--motion),border-color var(--motion),transform var(--motion) var(--ease); }
.recent-row:last-child { border-bottom-color:transparent; }
.recent-row:hover:not(:disabled) { background:#f2f8f6; border-color:#d7e9e2; transform:translateX(2px); }
.recent-row:active:not(:disabled) { transform:translateX(0); background:#e6f2ed; }
.recent-row:disabled { color:#69768a; background:transparent; }
.record-icon, .config-icon { display:grid; place-items:center; flex-shrink:0; width:37px; height:37px; border-radius:9px; color:#64809a; background:#eff4f9; }
.record-icon .studio-icon, .config-icon .studio-icon { width:18px; height:18px; }
.recent-main { min-width:0; flex:1; }
.recent-main strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13px; font-weight:600; }
.recent-main small { display:block; margin-top:4px; font-size:12px; color:var(--muted); }
.recent-row > .studio-icon:last-child, .current-config > .studio-icon:last-child { width:14px; height:14px; color:#8597ab; }
.current-config { display:flex; align-items:center; gap:12px; width:100%; padding:14px 8px; border:1px solid transparent; border-bottom-color:#edf1f6; border-radius:8px; background:transparent; color:var(--ink); text-align:left; transition:background var(--motion),border-color var(--motion),transform var(--motion) var(--ease); }
.current-config:hover { background:#f2f8f6; border-color:#d7e9e2; transform:translateX(2px); }
.current-config:active { transform:translateX(0); background:#e6f2ed; }
.current-config > span:nth-child(2) { min-width:0; flex:1; }
.current-config small { display:block; font-size:12px; color:var(--muted); }
.current-config strong { display:block; margin-top:3px; font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.current-config em { display:block; margin-top:3px; color:var(--muted); font-size:12px; font-style:normal; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.local-note { display:flex; align-items:flex-start; gap:7px; margin-top:15px; color:var(--muted); }
.local-note .studio-icon { width:14px; height:14px; margin-top:2px; }
.local-note p { font-size:12px; line-height:1.7; }
.empty-state { display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; padding:42px 22px; color:var(--muted); }
.empty-state.compact { padding:26px 16px; }
.empty-state .empty-icon { display:grid; place-items:center; width:48px; height:48px; margin-bottom:14px; border:1px solid #e3eaf2; border-radius:13px; background:#f3f6fa; color:#7d90a7; }
.empty-icon > .studio-icon { width:23px; height:23px; }
.empty-state h3 { color:#40536c; font-size:14px; font-weight:600; }
.empty-state p { max-width:450px; margin-top:8px; color:var(--muted); font-size:13px; line-height:1.8; }
.empty-state .text-button { margin-top:12px; }
.empty-state > .studio-icon { color:#7d90a7; }
.tall-empty { min-height:285px; }
.empty-tip { display:inline-flex; align-items:center; gap:7px; margin-top:22px; padding:7px 11px; border-radius:6px; background:#f1f5f9; color:#5e728a; font-size:12px; }
.empty-tip .studio-icon { width:15px; height:15px; }
.logs-panel { margin-top:20px; border:1px solid var(--line); border-radius:10px; background:#fff; overflow:hidden; }
.logs-panel summary { display:flex; align-items:center; justify-content:space-between; min-height:49px; padding:12px 17px; color:#566a82; font-size:12px; list-style:none; cursor:pointer; transition:background var(--motion); }
.logs-panel summary:hover { background:#f1f6fa; }
.logs-panel summary::-webkit-details-marker { display:none; }
.logs-panel summary > span { display:inline-flex; align-items:center; gap:8px; }
.logs-panel summary .studio-icon { width:15px; height:15px; transition:transform var(--motion) var(--ease); }
.logs-panel[open] summary > span:last-child .studio-icon { transform:rotate(90deg); }
.logs-toolbar { display:flex; align-items:center; justify-content:space-between; padding:0 17px 5px; color:var(--muted); font-size:12px; }
.log-output { margin:0 14px 14px; max-height:330px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; border-radius:8px; padding:16px; background:#172437; color:#c8d8e7; font:12px/1.85 Consolas,"Microsoft YaHei",monospace; }
.workspace-footer { display:flex; align-items:center; gap:12px; padding-top:26px; font-size:11px; color:#728198; }
.workspace-footer > span:first-child { font-weight:600; color:#566981; }
.workspace-footer > span:nth-child(2) { padding-left:12px; border-left:1px solid #d7e1ec; }
.footer-local { display:flex; align-items:center; gap:7px; margin-left:auto; }

/* Notices use semantic colors and short state transitions. */
.alert { display:flex; align-items:flex-start; gap:10px; margin-bottom:18px; padding:13px 15px; border:1px solid; border-radius:9px; font-size:13px; line-height:1.7; }
.alert > .studio-icon { width:18px; height:18px; margin-top:2px; }
.alert p { flex:1; overflow-wrap:anywhere; }
.alert-error { background:#fff3f4; border-color:#f0d1d6; color:#a33543; }
.alert-success { background:#edf8f3; border-color:#c9e6da; color:#166849; }
.alert-info { background:#eef5fb; border-color:#d3e4f0; color:#375f7d; }
.notice { align-items:center; }
.notice p { white-space:pre-line; }
.notice .icon-button { width:30px; height:30px; margin:-3px -5px -3px auto; color:inherit; }
.connection-alert { align-items:center; }
.connection-alert > div { flex:1; }
.connection-alert strong { font-weight:600; }
.connection-alert p { margin-top:3px; font-size:12px; }

/* Model and Zep presets share the same card and editor language. */
.config-layout { display:grid; grid-template-columns:minmax(0,1fr) minmax(330px,410px); align-items:start; gap:24px; }
.config-list-section { min-width:0; }
.list-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:36px; margin-bottom:12px; }
.list-heading h2 { font-size:15px; }
.list-heading h2 > span, .count-label { display:inline-flex; align-items:center; justify-content:center; min-width:22px; height:22px; margin-left:6px; padding:0 6px; border-radius:6px; background:#e9eff5; color:#5a6f88; font-size:12px; font-weight:600; font-variant-numeric:tabular-nums; vertical-align:middle; }
.preset-card { position:relative; margin-bottom:14px; padding:20px 20px 14px; transition:border-color var(--motion),box-shadow var(--motion),background var(--motion); }
.preset-card:hover { border-color:#bdcddd; box-shadow:0 5px 16px #1d37500a; }
.preset-card.selected { border-color:#91cdbb; background:#f9fdfb; box-shadow:inset 3px 0 0 var(--primary),var(--shadow); }
.preset-card.selected:hover { border-color:#55ac94; box-shadow:inset 3px 0 0 var(--primary),0 5px 16px #0d8a7010; }
.preset-card.editing { outline:2px solid #bfd0e5; outline-offset:3px; }
.preset-top { display:flex; align-items:center; gap:12px; }
.preset-icon { display:grid; place-items:center; flex-shrink:0; width:40px; height:40px; border-radius:10px; background:#eef3f9; color:#627d9b; }
.preset-card.selected .preset-icon { background:#e4f3ed; color:var(--primary); }
.preset-title { flex:1; min-width:0; }
.preset-title h3 { font-size:15px; overflow-wrap:anywhere; }
.preset-title > span { display:block; margin-top:3px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.model-name { display:inline-block; max-width:100%; margin-top:16px; padding:5px 9px; border:1px solid #e0e8f1; border-radius:6px; background:#f2f6fa; color:#4b617b; font-family:Consolas,"Microsoft YaHei",monospace; font-size:12px; overflow-wrap:anywhere; }
.preset-details { display:flex; flex-wrap:wrap; gap:12px; margin:12px 0 16px; color:var(--muted); font-size:12px; }
.preset-details > span { display:flex; align-items:center; gap:6px; }
.preset-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; padding-top:12px; border-top:1px solid #e7edf3; }
.preset-actions > div { display:flex; gap:5px; }
.preset-card.selected .preset-actions > .button:disabled { border-color:#cde5db; color:#387761; background:#eaf5ef; }
.section-footnote { display:flex; align-items:flex-start; gap:7px; margin-top:18px !important; color:var(--muted); font-size:12px; line-height:1.8; }
.section-footnote .studio-icon { width:15px; height:15px; margin-top:3px; }
.editor-panel { position:sticky; top:calc(84px + var(--desktop-titlebar-height, 0px)); padding:23px; }
.editor-title { display:flex; align-items:center; justify-content:space-between; gap:16px; padding-bottom:18px; margin-bottom:20px; border-bottom:1px solid #e8edf3; }
.editor-title h2 { margin-top:4px; font-size:18px; }
.editor-title .section-kicker { font-size:11px; letter-spacing:1px; }
.editor-panel fieldset { min-width:0; border:0; padding:0; margin:0; }
.form-field { margin-bottom:18px; }
.form-field label { display:inline-block; margin-bottom:7px; color:#3e526c; font-size:13px; font-weight:600; }
.optional, .field-en { margin-left:5px; color:var(--muted); font-size:12px; font-weight:400; }
.form-field :is(input,select) { display:block; width:100%; min-height:43px; padding:10px 12px; border:1px solid #cbd6e2; border-radius:8px; background:#fcfdff; color:var(--ink); font-size:13px; transition:border-color var(--motion),box-shadow var(--motion),background var(--motion); }
.form-field :is(input,select):hover:not(:disabled) { border-color:#9ab3bd; background:#fff; }
.form-field :is(input,select):focus { outline:none; border-color:var(--primary); box-shadow:0 0 0 3px #0d8a7019; background:#fff; }
.form-field :is(input,select):disabled { color:#738298; background:#f0f3f7; border-color:#dce3eb; cursor:wait; }
.form-field input::placeholder { color:#8996a8; font-size:12px; }
.form-field select { cursor:pointer; }
.field-help { margin-top:7px !important; color:var(--muted); font-size:12px; line-height:1.7; }
.input-with-button { position:relative; }
.input-with-button input { padding-right:44px; }
.input-with-button .icon-button { position:absolute; top:4px; right:4px; width:35px; height:35px; }
.saved-label { margin-left:6px; padding:2px 5px; border-radius:4px; background:#e6f4ed; color:#37765c; font-size:11px; font-weight:500; }
.field-label-row { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:7px; }
.field-label-row label { margin:0; }
.field-label-row .text-button { min-height:28px; padding:3px 5px; font-size:12px; }
.field-label-row .studio-icon { width:13px; height:13px; }
.form-actions { display:flex; gap:10px; margin-top:22px; }
.form-actions .button { flex:1; padding-left:10px; padding-right:10px; font-size:13px; }
.form-footer { margin-top:13px !important; color:var(--muted); font-size:12px; line-height:1.75; text-align:center; }
.form-feedback { display:flex; align-items:flex-start; gap:7px; padding:11px 12px; border:1px solid #cde5d9; border-radius:8px; background:#eef8f2; color:#2e6b4a; font-size:12px; line-height:1.75; overflow-wrap:anywhere; }
.form-feedback .studio-icon { width:15px; height:15px; margin-top:3px; }
.form-feedback.error { background:#fff1f3; border-color:#f0d4d9; color:#a13645; }
.form-feedback.info { background:#edf5fc; border-color:#d2e3f0; color:#3a6484; }
.rotation-card { display:flex; align-items:center; gap:16px; margin-bottom:24px; padding:20px 22px; background:#fbfefd; border-color:#cde5dc; }
.rotation-icon { display:grid; place-items:center; flex-shrink:0; width:43px; height:43px; border:1px solid #cee9dd; border-radius:11px; background:#e9f6f0; color:var(--primary); }
.rotation-copy { flex:1; min-width:0; }
.rotation-copy > div { display:flex; align-items:center; flex-wrap:wrap; gap:10px; }
.rotation-copy h2 { font-size:15px; }
.rotation-copy p { margin-top:5px; color:var(--muted); font-size:13px; line-height:1.65; }
.switch { display:inline-flex; align-items:center; flex-shrink:0; width:46px; height:28px; padding:3px; border:1px solid #a7b7c9; border-radius:99px; background:#aebdce; transition:background 200ms,border-color 200ms,box-shadow 200ms; }
.switch span { width:20px; height:20px; border-radius:50%; background:#fff; box-shadow:0 1px 3px #14274030; transform:translateX(0); transition:transform 200ms var(--ease); }
.switch.on { background:var(--primary); border-color:var(--primary); }
.switch.on span { transform:translateX(17px); }
.switch:hover:not(:disabled) { box-shadow:0 0 0 4px #0d8a7012; }
.switch:disabled { opacity:.55; }
.key-summary { display:flex; align-items:center; gap:8px; margin:18px 0 16px; color:var(--muted); font-size:12px; }
.key-summary .studio-icon { width:15px; height:15px; }
.group-explainer { display:flex; align-items:flex-start; gap:10px; margin-top:20px; padding:16px; border:1px solid #dce5ee; border-radius:10px; background:#edf3f9; color:#536c85; }
.group-explainer > .studio-icon { width:18px; height:18px; margin-top:2px; }
.group-explainer strong { font-size:13px; font-weight:600; }
.group-explainer p { margin-top:6px; font-size:12px; line-height:1.8; }
.checkbox-label { display:flex; align-items:flex-start; gap:9px; margin:20px 0 4px; color:#415870; font-size:13px; cursor:pointer; }
.checkbox-label input { width:17px; height:17px; margin-top:2px; accent-color:var(--primary); cursor:pointer; }
.checkbox-label small { display:block; margin-top:3px; color:var(--muted); font-size:12px; }

/* Records and backup lists. */
.records-panel, .backups-panel { margin-bottom:20px; padding:22px 24px; }
.records-panel > .section-title { margin-bottom:18px; }
.search-field { display:flex; align-items:center; gap:8px; min-height:38px; padding:6px 11px; border:1px solid #cdd8e4; border-radius:8px; background:#fbfcfe; color:#71869d; transition:border-color var(--motion),box-shadow var(--motion); }
.search-field:focus-within { border-color:var(--primary); box-shadow:0 0 0 3px #0d8a7015; }
.search-field .studio-icon { width:16px; height:16px; }
.search-field input { width:180px; max-width:100%; min-height:24px; border:0; outline:none; background:transparent; color:var(--ink); font-size:13px; }
.search-field input:focus-visible { outline:none; }
.search-field input::placeholder { color:#8393a6; }
.table-scroll { overflow-x:auto; }
.records-table { width:100%; border-collapse:collapse; text-align:left; }
.records-table th { padding:11px 12px; border-bottom:1px solid #dfe7ef; background:#f6f8fb; color:#64748b; font-size:12px; font-weight:500; white-space:nowrap; }
.records-table td { padding:15px 12px; border-bottom:1px solid #edf1f6; color:var(--muted); font-size:13px; vertical-align:middle; transition:background var(--motion); }
.records-table tbody tr:hover td { background:#f5faf8; }
.records-table th:first-child { border-radius:7px 0 0 7px; }
.records-table th:last-child { border-radius:0 7px 7px 0; }
.records-table th:last-child, .records-table td:last-child { text-align:right; }
.records-table tbody tr:last-child td { border-bottom:0; }
.records-table td:nth-child(2) { white-space:nowrap; font-size:12px; font-variant-numeric:tabular-nums; }
.table-project { display:flex; align-items:center; gap:12px; min-width:175px; max-width:440px; }
.table-project strong { display:block; color:#2f455f; font-size:13px; font-weight:600; overflow-wrap:anywhere; }
.table-project small { display:block; margin-top:4px; color:var(--muted); font-size:12px; }
.card-bottom-note { padding-top:13px; border-top:1px solid #e8edf3; color:var(--muted); font-size:12px; }
.section-subtitle { margin-top:5px !important; color:var(--muted); font-size:12px; }
.backup-list { margin-top:16px; }
.backup-row { display:flex; align-items:center; gap:13px; padding:15px 10px; border-bottom:1px solid #e8edf4; border-radius:8px; transition:background var(--motion); }
.backup-row:last-child { border-bottom-color:transparent; }
.backup-row:hover { background:#f7fafc; }
.backup-file-icon { display:grid; place-items:center; flex-shrink:0; width:38px; height:42px; border-radius:9px; background:#edf3f9; color:#68829e; }
.backup-file-icon .studio-icon { width:19px; height:19px; }
.backup-details { min-width:0; flex:1; }
.backup-details strong { display:block; color:#3e5670; font-size:13px; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.backup-details small { display:block; margin-top:5px; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
.backup-details small > span { padding:0 5px; color:#9aaaae; }
.backup-guidance { display:flex; align-items:flex-start; gap:10px; margin-top:17px; padding:15px; border:1px solid #dce6ef; border-radius:9px; background:#f3f7fb; color:#60738a; }
.backup-guidance .studio-icon { width:16px; height:16px; margin-top:3px; }
.backup-guidance > div { min-width:0; }
.backup-guidance p { font-size:12px; line-height:1.85; }
.path-note { margin-top:5px !important; }
.path-note code { margin-left:5px; font:inherit; overflow-wrap:anywhere; color:#4b647e; }

/* Form drafts live in script setup; only the visible keyed pane changes. */
.workspace-pane-enter-active { transition:opacity 220ms var(--ease),transform 220ms var(--ease); }
.workspace-pane-leave-active { transition:opacity 160ms ease-in,transform 160ms ease-in; pointer-events:none; }
.workspace-pane-enter-from { opacity:0; transform:translateY(9px); }
.workspace-pane-leave-to { opacity:0; transform:translateY(-4px); }
.feedback-enter-active { transition:opacity 200ms var(--ease),transform 200ms var(--ease); }
.feedback-leave-active { transition:opacity 160ms ease-in,transform 160ms ease-in; }
.feedback-enter-from, .feedback-leave-to { opacity:0; transform:translateY(-5px); }
.spinning { animation:studio-spin 1s linear infinite; }
@keyframes studio-spin { to { transform:rotate(360deg); } }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; }

/* Visible navigation labels stay available at every desktop size. */
@media (min-width:1600px) {
  .workspace { padding-top:34px; }
  .dashboard-top, .dashboard-bottom { grid-template-columns:minmax(0,1.6fr) minmax(350px,1fr); }
  .config-layout { grid-template-columns:minmax(0,1fr) 430px; gap:28px; }
}
@media (max-width:1200px) {
  .studio-sidebar { width:208px; padding-left:13px; padding-right:13px; }
  .studio-main { margin-left:208px; }
  .workspace { padding:25px 24px 20px; }
  .topbar { padding:0 24px; }
  .dashboard-top { grid-template-columns:minmax(0,1.3fr) minmax(280px,1fr); gap:16px; }
  .dashboard-bottom { grid-template-columns:minmax(0,1.2fr) minmax(270px,1fr); gap:16px; }
  .launch-card, .engine-card { padding-left:20px; padding-right:20px; }
  .launch-copy h2 { font-size:18px; }
  .launch-copy p { font-size:12px; }
  .setup-summary { min-width:58px; padding:8px; }
  .stat-grid { gap:16px; }
  .stat-card { gap:12px; padding:17px; }
  .stat-caption { display:none; }
  .config-layout { grid-template-columns:minmax(0,1fr) minmax(320px,360px); gap:20px; }
  .editor-panel { padding:21px; }
  .preset-card { padding:18px 18px 13px; }
  .preset-top { gap:10px; flex-wrap:wrap; }
  .preset-title { min-width:120px; }
  .preset-top > .badge { margin-left:auto; }
  .page-heading h1 { font-size:25px; }
}
@media (max-width:1020px) {
  .studio-sidebar { width:180px; padding:25px 10px 18px; }
  .studio-main { margin-left:180px; }
  .studio-brand { gap:8px; padding:0 4px; }
  .brand-symbol { width:32px; height:35px; border-radius:9px; }
  .brand-type { font-size:18px; }
  .brand-type > span { gap:5px; letter-spacing:1.5px; }
  .studio-nav button { gap:10px; padding-left:11px; padding-right:11px; font-size:13px; }
  .sidebar-label { margin-left:11px; }
  .sidebar-bottom { padding-left:0; padding-right:0; }
  .sidebar-note { gap:8px; padding-left:4px; }
  .studio-connection { font-size:11px; gap:6px; }
  .workspace { padding:24px 20px 20px; }
  .topbar { padding-left:20px; padding-right:20px; }
  .topbar-actions { gap:10px; }
  .config-layout { grid-template-columns:minmax(0,1fr) minmax(300px,340px); gap:18px; }
  .editor-panel { padding:19px; }
  .page-description { font-size:13px; }
  .launch-card, .engine-card { padding-left:18px; padding-right:18px; }
  .engine-visual { font-size:18px; }
  .recent-card, .current-card { padding:19px 17px; }
  .quiet-label { font-size:11px; }
}
@media (max-width:860px) {
  .studio-sidebar { width:166px; }
  .studio-main { margin-left:166px; }
  .brand-symbol { width:29px; height:32px; }
  .brand-symbol .studio-icon { width:23px; height:23px; }
  .brand-type { font-size:17px; }
  .brand-type i { display:none; }
  .studio-nav button { gap:8px; padding-left:10px; }
  .studio-nav .nav-arrow { display:none; }
  .sidebar-note small { font-size:11px; }
  .sidebar-note > .studio-icon { width:16px; height:16px; }
  .topbar-status { display:none; }
  .dashboard-top, .dashboard-bottom, .config-layout { grid-template-columns:1fr; }
  .editor-panel { position:static; padding:22px; }
  .engine-card { padding:21px; }
  .engine-visual { margin-top:20px; }
  .engine-message { min-height:0; }
  .engine-foot { padding-top:17px; }
  .launch-copy p { font-size:13px; }
  .launch-card { padding:21px; }
  .launch-copy h2 { font-size:20px; }
  .page-heading { align-items:flex-start; gap:15px; }
  .page-heading > .button { margin-top:3px; padding-left:12px; padding-right:12px; }
  .page-heading > .button > .studio-icon:last-child:not(:first-child) { display:none; }
  .stat-card { padding:15px 13px; gap:9px; }
  .stat-icon { width:32px; height:35px; border-radius:8px; }
  .stat-icon .studio-icon { width:17px; height:17px; }
  .stat-card strong { font-size:24px; }
  .empty-tip { display:none; }
  .tall-empty { min-height:220px; }
  .preset-top { flex-wrap:nowrap; }
  .records-panel, .backups-panel { padding:20px; }
  .rotation-card { gap:12px; padding:18px; }
  .rotation-copy p { font-size:12px; }
  .records-table { min-width:540px; }
  .search-field input { width:145px; }
}
@media (max-width:600px) {
  .studio-shell { display:block; }
  .studio-sidebar { position:static; width:100%; min-height:0; padding:16px; display:block; }
  .studio-main { margin-left:0; }
  .studio-brand { margin-left:4px; gap:9px; }
  .brand-type { display:flex; align-items:baseline; gap:9px; font-size:20px; }
  .brand-type > span { display:flex; gap:8px; margin-top:0; font-size:10px; }
  .brand-type i { display:inline; }
  .brand-symbol { width:31px; height:33px; }
  .sidebar-label, .sidebar-bottom { display:none; }
  .studio-nav { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:5px; margin-top:16px; }
  .studio-nav button { display:flex; flex-direction:column; justify-content:center; gap:5px; min-height:57px; padding:7px 2px; font-size:12px; border-radius:8px; }
  .studio-nav button::before { top:auto; bottom:-1px; left:25%; right:25%; width:auto; height:2px; border-radius:2px; transform:scaleX(.3); }
  .studio-nav button.active::before { transform:scaleX(1); }
  .studio-nav button:hover { transform:translateY(-1px); }
  .studio-nav button > .studio-icon { width:18px; height:18px; }
  .topbar { position:static; min-height:54px; padding:0 19px; }
  .topbar-actions { gap:8px; }
  .breadcrumb { gap:8px; font-size:12px; }
  .workspace { min-height:calc(100vh - 180px); padding:23px 17px 20px; }
  .page-heading { flex-direction:column; gap:15px; margin-bottom:20px; }
  .page-heading h1 { font-size:25px; }
  .page-description { line-height:1.7; font-size:13px; }
  .page-heading > .button { margin-top:0; min-height:43px; }
  .launch-card { padding:20px 17px 15px; }
  .launch-copy { gap:10px; }
  .launch-copy h2 { font-size:18px; }
  .launch-copy p { font-size:12px; }
  .setup-summary { min-width:55px; min-height:62px; }
  .setup-summary strong { font-size:23px; }
  .setup-step { min-height:61px; gap:10px; padding-left:10px; padding-right:10px; }
  .setup-step small { white-space:normal; }
  .dashboard-top, .dashboard-bottom { gap:16px; }
  .stat-grid { gap:9px; margin-top:16px; }
  .stat-card { flex-direction:column; align-items:flex-start; gap:10px; padding:15px 13px; border-radius:11px; }
  .stat-label { font-size:11px; }
  .dashboard-bottom { margin-top:16px; }
  .recent-card, .current-card { padding:20px 17px; }
  .recent-row { gap:9px; padding-left:4px; padding-right:4px; }
  .recent-row > .studio-icon:last-child { display:none; }
  .recent-row > .badge { font-size:11px; padding-left:5px; padding-right:5px; }
  .recent-main strong { font-size:12px; }
  .workspace-footer { flex-wrap:wrap; gap:8px; font-size:11px; padding-top:24px; }
  .footer-local { width:100%; margin-left:0; }
  .workspace-footer > span:nth-child(2) { padding-left:8px; }
  .alert { padding:12px; font-size:12px; }
  .connection-alert { flex-wrap:wrap; }
  .connection-alert > div { flex:1 1 210px; }
  .connection-alert .button { margin-left:27px; }
  .config-layout { gap:20px; }
  .list-heading h2 { font-size:14px; }
  .preset-card { padding:19px 17px 13px; }
  .preset-icon { width:36px; height:38px; }
  .preset-title { min-width:0; }
  .preset-title h3 { font-size:14px; }
  .preset-top { gap:10px; flex-wrap:wrap; }
  .preset-top > .badge { font-size:11px; }
  .editor-panel { padding:21px 18px; }
  .form-field :is(input,select) { min-height:46px; font-size:16px; }
  .input-with-button .icon-button { top:5px; right:5px; }
  .form-actions .button { min-height:44px; }
  .rotation-icon { display:none; }
  .rotation-card { padding:18px; }
  .rotation-copy > div { gap:7px; }
  .rotation-copy h2 { font-size:14px; }
  .rotation-copy > div .badge { font-size:11px; }
  .switch { width:44px; }
  .switch.on span { transform:translateX(15px); }
  .records-panel, .backups-panel { padding:20px 16px; }
  .records-panel > .section-title { flex-direction:column; align-items:flex-start; gap:13px; }
  .search-field { width:100%; }
  .search-field input { width:100%; min-height:28px; font-size:16px; }
  .backup-row { flex-wrap:wrap; gap:10px; padding-left:0; padding-right:0; }
  .backup-details { flex-basis:calc(100% - 48px); }
  .backup-row > .button { margin-left:48px; min-height:40px; }
  .backup-guidance { padding:12px; gap:8px; }
}
@media (hover:none) {
  .icon-button { width:44px; height:44px; }
  .input-with-button .icon-button { width:38px; height:38px; }
  .text-button { min-height:44px; }
  .button-small { min-height:42px; }
  .field-label-row .text-button { min-height:36px; }
}
@media (prefers-reduced-motion:reduce) {
  .studio-shell *, .studio-shell *::before, .studio-shell *::after { scroll-behavior:auto !important; transition-duration:.01ms !important; animation-duration:.01ms !important; animation-iteration-count:1 !important; }
  .workspace-pane-enter-from, .workspace-pane-leave-to, .feedback-enter-from, .feedback-leave-to { transform:none; }
}
</style>
