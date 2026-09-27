<template>
  <div class="env-setup-panel">
    <div class="scroll-container">
      <section class="preparation-state" :class="{ 'has-error': prepareError || actionError, 'has-warning': connectionWarning }" :aria-busy="isRestoring || prepareSubmitting" aria-live="polite">
        <div class="preparation-state-copy">
          <span class="preparation-eyebrow">环境准备进度</span>
          <h3>{{ preparationTitle }}</h3>
          <p v-if="prepareError || actionError" role="alert">{{ prepareError || actionError }}</p>
          <p v-else>{{ preparationDescription }}</p>
          <p v-if="prepareError">可先恢复查看最新状态，或检查模型与 Zep 连接后手动重试环境准备。</p>
          <p v-if="connectionWarning" class="connection-warning" role="status">{{ connectionWarning }} 已有资料保留在本地，恢复连接后会继续读取进度。</p>
          <p v-if="preparationReady && configIssue && !connectionWarning" class="connection-warning">{{ configIssue }} 请先恢复查看，确认资料完整后再进入推演。</p>
        </div>
        <div class="preparation-actions">
          <button type="button" class="preparation-btn secondary" :disabled="isRestoring || prepareSubmitting" @click="restorePreparation()">{{ isRestoring ? '正在读取…' : '恢复查看' }}</button>
          <button v-if="canRetryPrepare" type="button" class="preparation-btn" :disabled="isRestoring || prepareSubmitting || !!connectionWarning" @click="retryPreparation">{{ prepareError ? '重试环境准备' : '开始环境准备' }}</button>
        </div>
      </section>
      <!-- Step 01: 模拟实例 -->
      <div class="step-card" :class="{ 'active': phase === 0, 'completed': phase > 0 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">01</span>
            <span class="step-title">{{ $t('step2.simInstanceInit') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 0" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else class="badge processing">{{ $t('step2.initializing') }}</span>
          </div>
        </div>
        
        <div class="card-content">
          <p class="description">
            {{ $t('step2.simInstanceDesc') }}
          </p>

          <div v-if="simulationId" class="info-card">
            <div class="info-row">
              <span class="info-label">项目编号</span>
              <span class="info-value mono">{{ projectData?.project_id }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">图谱编号</span>
              <span class="info-value mono">{{ projectData?.graph_id }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">推演编号</span>
              <span class="info-value mono">{{ simulationId }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">准备任务</span>
              <span class="info-value mono">{{ taskId || (preparationReady ? '已完成' : '等待确认') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 02: 生成 Agent 人设 -->
      <div class="step-card" :class="{ 'active': phase === 1, 'completed': phase > 1 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">02</span>
            <span class="step-title">{{ $t('step2.generateAgentPersona') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 1" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else-if="phase === 1" class="badge" :class="prepareError ? 'error' : 'processing'">{{ prepareError ? '准备失败' : (prepareProgress === null ? '正在准备' : `${prepareProgress}%`) }}</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="description">
            {{ $t('step2.generateAgentPersonaDesc') }}
          </p>

          <!-- Profiles Stats -->
          <div v-if="profiles.length > 0" class="stats-grid">
            <div class="stat-card">
              <span class="stat-value">{{ profiles.length }}</span>
              <span class="stat-label">{{ $t('step2.currentAgentCount') }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ expectedTotal || '-' }}</span>
              <span class="stat-label">{{ $t('step2.expectedAgentTotal') }}</span>
            </div>
            <div class="stat-card">
              <span class="stat-value">{{ totalTopicsCount }}</span>
              <span class="stat-label">{{ $t('step2.relatedTopicsCount') }}</span>
            </div>
          </div>

          <!-- Profiles List Preview -->
          <div v-if="profiles.length > 0" class="profiles-preview">
            <div class="preview-header">
              <span class="preview-title">{{ $t('step2.generatedAgentPersonas') }}</span>
            </div>
            <div class="profiles-list">
              <div 
                v-for="(profile, idx) in profiles" 
                :key="idx" 
                class="profile-card"
                @click="selectProfile(profile)"
              >
                <div class="profile-header">
                  <span class="profile-realname">{{ profile.username || '未命名角色' }}</span>
                  <span class="profile-username">@{{ profile.name || `agent_${idx}` }}</span>
                </div>
                <div class="profile-meta">
                  <span class="profile-profession">{{ profile.profession || $t('step2.unknownProfession') }}</span>
                </div>
                <p class="profile-bio">{{ profile.bio || $t('step2.noBio') }}</p>
                <div v-if="profile.interested_topics?.length" class="profile-topics">
                  <span 
                    v-for="topic in profile.interested_topics.slice(0, 3)" 
                    :key="topic" 
                    class="topic-tag"
                  >{{ topic }}</span>
                  <span v-if="profile.interested_topics.length > 3" class="topic-more">
                    +{{ profile.interested_topics.length - 3 }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 03: 生成双平台模拟配置 -->
      <div class="step-card" :class="{ 'active': phase === 2, 'completed': phase > 2 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">03</span>
            <span class="step-title">{{ $t('step2.dualPlatformConfig') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 2" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else-if="phase === 2" class="badge" :class="prepareError ? 'error' : 'processing'">{{ prepareError ? '准备失败' : '正在生成' }}</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="description">
            {{ $t('step2.dualPlatformConfigDesc') }}
          </p>
          
          <!-- Config Preview -->
          <div v-if="simulationConfig" class="config-detail-panel">
            <!-- 时间配置 -->
            <div class="config-block">
              <div class="config-grid">
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.simulationDuration') }}</span>
                  <span class="config-item-value">{{ simulationConfig.time_config?.total_simulation_hours || '-' }} {{ $t('common.hours') }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.roundDuration') }}</span>
                  <span class="config-item-value">{{ simulationConfig.time_config?.minutes_per_round || '-' }} {{ $t('common.minutes') }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.totalRounds') }}</span>
                  <span class="config-item-value">{{ autoGeneratedRounds || '-' }} {{ $t('common.rounds') }}</span>
                </div>
                <div class="config-item">
                  <span class="config-item-label">{{ $t('step2.activePerHour') }}</span>
                  <span class="config-item-value">{{ simulationConfig.time_config?.agents_per_hour_min }}-{{ simulationConfig.time_config?.agents_per_hour_max }}</span>
                </div>
              </div>
              <div class="time-periods">
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.peakHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.peak_hours?.join(':00, ') }}:00</span>
                  <span class="period-multiplier">×{{ simulationConfig.time_config?.peak_activity_multiplier }}</span>
                </div>
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.workHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.work_hours?.[0] }}:00-{{ simulationConfig.time_config?.work_hours?.slice(-1)[0] }}:00</span>
                  <span class="period-multiplier">×{{ simulationConfig.time_config?.work_activity_multiplier }}</span>
                </div>
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.morningHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.morning_hours?.[0] }}:00-{{ simulationConfig.time_config?.morning_hours?.slice(-1)[0] }}:00</span>
                  <span class="period-multiplier">×{{ simulationConfig.time_config?.morning_activity_multiplier }}</span>
                </div>
                <div class="period-item">
                  <span class="period-label">{{ $t('step2.offPeakHours') }}</span>
                  <span class="period-hours">{{ simulationConfig.time_config?.off_peak_hours?.[0] }}:00-{{ simulationConfig.time_config?.off_peak_hours?.slice(-1)[0] }}:00</span>
                  <span class="period-multiplier">×{{ simulationConfig.time_config?.off_peak_activity_multiplier }}</span>
                </div>
              </div>
            </div>

            <!-- Agent 配置 -->
            <div class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.agentConfig') }}</span>
                <span class="config-block-badge">{{ simulationConfig.agent_configs?.length || 0 }} {{ $t('common.items') }}</span>
              </div>
              <div class="agents-cards">
                <div 
                  v-for="agent in simulationConfig.agent_configs" 
                  :key="agent.agent_id" 
                  class="agent-card"
                >
                  <!-- 卡片头部 -->
                  <div class="agent-card-header">
                    <div class="agent-identity">
                      <span class="agent-id">角色 {{ agent.agent_id }}</span>
                      <span class="agent-name">{{ agent.entity_name }}</span>
                    </div>
                    <div class="agent-tags">
                      <span class="agent-type">{{ agent.entity_type }}</span>
                      <span class="agent-stance" :class="'stance-' + agent.stance">{{ stanceLabel(agent.stance) }}</span>
                    </div>
                  </div>
                  
                  <!-- 活跃时间轴 -->
                  <div class="agent-timeline">
                    <span class="timeline-label">{{ $t('step2.activeTimePeriod') }}</span>
                    <div class="mini-timeline">
                      <div 
                        v-for="hour in 24" 
                        :key="hour - 1" 
                        class="timeline-hour"
                        :class="{ 'active': agent.active_hours?.includes(hour - 1) }"
                        :title="`${hour - 1}:00`"
                      ></div>
                    </div>
                    <div class="timeline-marks">
                      <span>0</span>
                      <span>6</span>
                      <span>12</span>
                      <span>18</span>
                      <span>24</span>
                    </div>
                  </div>

                  <!-- 行为参数 -->
                  <div class="agent-params">
                    <div class="param-group">
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.postsPerHour') }}</span>
                        <span class="param-value">{{ agent.posts_per_hour }}</span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.commentsPerHour') }}</span>
                        <span class="param-value">{{ agent.comments_per_hour }}</span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.responseDelay') }}</span>
                        <span class="param-value">{{ agent.response_delay_min }}-{{ agent.response_delay_max }}min</span>
                      </div>
                    </div>
                    <div class="param-group">
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.activityLevel') }}</span>
                        <span class="param-value with-bar">
                          <span class="mini-bar" :style="{ width: (agent.activity_level * 100) + '%' }"></span>
                          {{ (agent.activity_level * 100).toFixed(0) }}%
                        </span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.sentimentBias') }}</span>
                        <span class="param-value" :class="agent.sentiment_bias > 0 ? 'positive' : agent.sentiment_bias < 0 ? 'negative' : 'neutral'">
                          {{ agent.sentiment_bias > 0 ? '+' : '' }}{{ agent.sentiment_bias?.toFixed(1) }}
                        </span>
                      </div>
                      <div class="param-item">
                        <span class="param-label">{{ $t('step2.influenceWeight') }}</span>
                        <span class="param-value highlight">{{ agent.influence_weight?.toFixed(1) }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 平台配置 -->
            <div class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.recommendAlgoConfig') }}</span>
              </div>
              <div class="platforms-grid">
                <div v-if="simulationConfig.twitter_config" class="platform-card">
                  <div class="platform-card-header">
                    <span class="platform-name">{{ $t('step2.platform1Name') }}</span>
                  </div>
                  <div class="platform-params">
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.recencyWeight') }}</span>
                      <span class="param-value">{{ simulationConfig.twitter_config.recency_weight }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.popularityWeight') }}</span>
                      <span class="param-value">{{ simulationConfig.twitter_config.popularity_weight }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.relevanceWeight') }}</span>
                      <span class="param-value">{{ simulationConfig.twitter_config.relevance_weight }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.viralThreshold') }}</span>
                      <span class="param-value">{{ simulationConfig.twitter_config.viral_threshold }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.echoChamberStrength') }}</span>
                      <span class="param-value">{{ simulationConfig.twitter_config.echo_chamber_strength }}</span>
                    </div>
                  </div>
                </div>
                <div v-if="simulationConfig.reddit_config" class="platform-card">
                  <div class="platform-card-header">
                    <span class="platform-name">{{ $t('step2.platform2Name') }}</span>
                  </div>
                  <div class="platform-params">
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.recencyWeight') }}</span>
                      <span class="param-value">{{ simulationConfig.reddit_config.recency_weight }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.popularityWeight') }}</span>
                      <span class="param-value">{{ simulationConfig.reddit_config.popularity_weight }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.relevanceWeight') }}</span>
                      <span class="param-value">{{ simulationConfig.reddit_config.relevance_weight }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.viralThreshold') }}</span>
                      <span class="param-value">{{ simulationConfig.reddit_config.viral_threshold }}</span>
                    </div>
                    <div class="param-row">
                      <span class="param-label">{{ $t('step2.echoChamberStrength') }}</span>
                      <span class="param-value">{{ simulationConfig.reddit_config.echo_chamber_strength }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- LLM 配置推理 -->
            <div v-if="simulationConfig.generation_reasoning" class="config-block">
              <div class="config-block-header">
                <span class="config-block-title">{{ $t('step2.llmConfigReasoning') }}</span>
              </div>
              <div class="reasoning-content">
                <div 
                  v-for="(reason, idx) in simulationConfig.generation_reasoning.split('|').slice(0, 2)" 
                  :key="idx" 
                  class="reasoning-item"
                >
                  <p class="reasoning-text">{{ reason.trim() }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 04: 初始激活编排 -->
      <div class="step-card" :class="{ 'active': phase === 3, 'completed': phase > 3 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">04</span>
            <span class="step-title">{{ $t('step2.initialActivation') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase > 3" class="badge success">{{ $t('common.completed') }}</span>
            <span v-else-if="phase === 3" class="badge" :class="prepareError ? 'error' : 'processing'">{{ prepareError ? '准备失败' : '正在核对' }}</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="description">
            {{ $t('step2.initialActivationDesc') }}
          </p>

          <div v-if="simulationConfig?.event_config" class="orchestration-content">
            <!-- 叙事方向 -->
            <div class="narrative-box">
              <span class="box-label narrative-label">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="special-icon">
                  <path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22Z" stroke="url(#paint0_linear)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M16.24 7.76L14.12 14.12L7.76 16.24L9.88 9.88L16.24 7.76Z" fill="url(#paint0_linear)" stroke="url(#paint0_linear)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                  <defs>
                    <linearGradient id="paint0_linear" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
                      <stop stop-color="#FF5722"/>
                      <stop offset="1" stop-color="#FF9800"/>
                    </linearGradient>
                  </defs>
                </svg>
                {{ $t('step2.narrativeDirection') }}
              </span>
              <p class="narrative-text">{{ simulationConfig.event_config.narrative_direction }}</p>
            </div>

            <!-- 热点话题 -->
            <div class="topics-section">
              <span class="box-label">{{ $t('step2.initialHotTopics') }}</span>
              <div class="hot-topics-grid">
                <span v-for="topic in simulationConfig.event_config.hot_topics" :key="topic" class="hot-topic-tag">
                  # {{ topic }}
                </span>
              </div>
            </div>

            <!-- 初始帖子流 -->
            <div class="initial-posts-section">
              <span class="box-label">{{ $t('step2.initialActivationSeq', { count: simulationConfig.event_config.initial_posts?.length || 0 }) }}</span>
              <div class="posts-timeline">
                <div v-for="(post, idx) in simulationConfig.event_config.initial_posts" :key="idx" class="timeline-item">
                  <div class="timeline-marker"></div>
                  <div class="timeline-content">
                    <div class="post-header">
                      <span class="post-role">{{ post.poster_type }}</span>
                      <span class="post-agent-info">
                        <span class="post-id">角色 {{ post.poster_agent_id }}</span>
                        <span class="post-username">@{{ getAgentUsername(post.poster_agent_id) }}</span>
                      </span>
                    </div>
                    <p class="post-text">{{ post.content }}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 05: 准备完成 -->
      <div class="step-card" :class="{ 'active': phase === 4 }">
        <div class="card-header">
          <div class="step-info">
            <span class="step-num">05</span>
            <span class="step-title">{{ $t('step2.setupComplete') }}</span>
          </div>
          <div class="step-status">
            <span v-if="phase >= 4" class="badge success">准备就绪</span>
            <span v-else class="badge pending">{{ $t('common.pending') }}</span>
          </div>
        </div>

        <div class="card-content">
          <p class="description">{{ $t('step2.setupCompleteDesc') }}</p>
          
          <!-- 模拟轮数配置 - 只有在配置生成完成且轮数计算出来后才显示 -->
          <div v-if="simulationConfig && autoGeneratedRounds" class="rounds-config-section">
            <div class="rounds-header">
              <div class="header-left">
                <span class="section-title">{{ $t('step2.roundsConfig') }}</span>
                <span class="section-desc">{{ $t('step2.roundsConfigDesc', { hours: simulationConfig?.time_config?.total_simulation_hours || '-', minutesPerRound: simulationConfig?.time_config?.minutes_per_round || '-' }) }}</span>
              </div>
              <button type="button" class="switch-control" :class="{ checked: useCustomRounds }" role="switch" :aria-checked="useCustomRounds" aria-label="自定义推演轮数" @click="useCustomRounds = !useCustomRounds">
                <span class="switch-track" aria-hidden="true"></span>
                <span class="switch-label">{{ $t('step2.customToggle') }}</span>
              </button>
            </div>
            
            <Transition name="fade" mode="out-in">
              <div v-if="useCustomRounds" class="rounds-content custom" key="custom">
                <div class="slider-display">
                  <div class="slider-main-value">
                    <input type="number" class="val-num rounds-number" v-model.number="customMaxRounds" min="1" :max="autoGeneratedRounds" step="1" aria-label="推演轮数" :aria-invalid="!roundsValid" aria-describedby="rounds-guidance" @blur="normalizeRounds">
                    <span class="val-unit">{{ $t('step2.roundsUnit') }}</span>
                  </div>
                  <div class="slider-meta-info">
                    <span id="rounds-guidance">先用 {{ recommendedRounds }} 轮验证；轮数越多，调用开销通常越高</span>
                  </div>
                </div>

                <div class="range-wrapper">
                  <input 
                    type="range" 
                    v-model.number="customMaxRounds" 
                    min="1" 
                    :max="autoGeneratedRounds"
                    step="1"
                    aria-label="拖动设置推演轮数"
                    class="minimal-slider"
                    :style="{ '--percent': roundsSliderPercent + '%' }"
                  />
                  <div class="range-marks">
                    <span>1</span>
                    <button type="button"
                      class="mark-recommend" 
                      :class="{ active: customMaxRounds === recommendedRounds }"
                      @click="customMaxRounds = recommendedRounds"
                    >建议先试 {{ recommendedRounds }} 轮</button>
                    <span>{{ autoGeneratedRounds }}</span>
                  </div>
                </div>
              </div>
              
              <div v-else class="rounds-content auto" key="auto">
                <div class="auto-info-card">
                  <div class="auto-value">
                    <span class="val-num">{{ autoGeneratedRounds }}</span>
                    <span class="val-unit">{{ $t('step2.roundsUnit') }}</span>
                  </div>
                  <div class="auto-content">
                    <div class="auto-meta-row">
                      <span class="duration-badge">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <circle cx="12" cy="12" r="10"></circle>
                          <polyline points="12 6 12 12 16 14"></polyline>
                        </svg>
                        按生成的时间配置完成全部轮次
                      </span>
                    </div>
                    <div class="auto-desc">
                      <button type="button" class="highlight-tip" @click="useCustomRounds = true">改为少量轮次，先验证效果 ➝</button>
                    </div>
                  </div>
                </div>
              </div>
            </Transition>
            <p v-if="useCustomRounds && !roundsValid" class="rounds-error" role="status">请输入 1 到 {{ autoGeneratedRounds }} 之间的整数轮数。</p>
          </div>

          <div class="action-group dual">
            <button 
              class="action-btn secondary"
              @click="$emit('go-back')"
            >
              ← {{ $t('step2.backToGraphBuild') }}
            </button>
            <button 
              class="action-btn primary"
              :disabled="!canStartSimulation"
              @click="handleStartSimulation"
            >
              {{ $t('step2.startDualWorldSim') }} ➝
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Profile Detail Modal -->
    <Transition name="modal">
      <div v-if="selectedProfile" class="profile-modal-overlay" @click.self="selectedProfile = null">
        <div class="profile-modal">
          <div class="modal-header">
          <div class="modal-header-info">
            <div class="modal-name-row">
              <span class="modal-realname">{{ selectedProfile.username }}</span>
              <span class="modal-username">@{{ selectedProfile.name }}</span>
            </div>
            <span class="modal-profession">{{ selectedProfile.profession }}</span>
          </div>
          <button class="close-btn" aria-label="关闭角色详情" @click="selectedProfile = null">×</button>
        </div>
        
        <div class="modal-body">
          <!-- 基本信息 -->
          <div class="modal-info-grid">
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalAge') }}</span>
              <span class="info-value">{{ selectedProfile.age || '-' }} {{ $t('step2.yearsOld') }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalGender') }}</span>
              <span class="info-value">{{ { male: $t('step2.genderMale'), female: $t('step2.genderFemale'), other: $t('step2.genderOther') }[selectedProfile.gender] || selectedProfile.gender }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalCountry') }}</span>
              <span class="info-value">{{ selectedProfile.country || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">{{ $t('step2.profileModalMbti') }}</span>
              <span class="info-value mbti">{{ selectedProfile.mbti || '-' }}</span>
            </div>
          </div>

          <!-- 简介 -->
          <div class="modal-section">
            <span class="section-label">{{ $t('step2.profileModalBio') }}</span>
            <p class="section-bio">{{ selectedProfile.bio || $t('step2.noBio') }}</p>
          </div>

          <!-- 关注话题 -->
          <div class="modal-section" v-if="selectedProfile.interested_topics?.length">
            <span class="section-label">{{ $t('step2.profileModalTopics') }}</span>
            <div class="topics-grid">
              <span 
                v-for="topic in selectedProfile.interested_topics" 
                :key="topic" 
                class="topic-item"
              >{{ topic }}</span>
            </div>
          </div>

          <!-- 详细人设 -->
          <div class="modal-section" v-if="selectedProfile.persona">
            <span class="section-label">{{ $t('step2.profileModalPersona') }}</span>
            
            <!-- 人设维度概览 -->
            <div class="persona-dimensions">
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimExperience') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimExperienceDesc') }}</span>
              </div>
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimBehavior') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimBehaviorDesc') }}</span>
              </div>
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimMemory') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimMemoryDesc') }}</span>
              </div>
              <div class="dimension-card">
                <span class="dim-title">{{ $t('step2.personaDimSocial') }}</span>
                <span class="dim-desc">{{ $t('step2.personaDimSocialDesc') }}</span>
              </div>
            </div>

            <div class="persona-content">
              <p class="section-persona">{{ selectedProfile.persona }}</p>
            </div>
          </div>
        </div>
      </div>
      </div>
    </Transition>

    <!-- Bottom Info / Logs -->
    <div class="system-logs">
      <div class="log-header">
        <span class="log-title">准备记录</span>
        <span class="log-id">{{ simulationId || '尚未创建推演' }}</span>
      </div>
      <div class="log-content" ref="logContent">
        <div class="log-line" v-for="(log, idx) in systemLogs" :key="idx">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-msg">{{ log.msg }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onUnmounted, nextTick } from 'vue'
import {
  prepareSimulation,
  getSimulation,
  getPrepareStatus,
  getSimulationProfilesRealtime,
  getSimulationConfigRealtime
} from '../api/simulation'

const props = defineProps({
  simulationId: String,
  projectData: Object,
  graphData: Object,
  systemLogs: Array
})
const emit = defineEmits(['go-back', 'next-step', 'add-log', 'update-status'])

const phase = ref(0)
const taskId = ref(null)
const prepareProgress = ref(null)
const currentStage = ref('')
const profiles = ref([])
const expectedTotal = ref(null)
const simulationConfig = ref(null)
const selectedProfile = ref(null)
const currentSimulation = ref(null)
const preparationStatus = ref('loading')
const preparationReady = ref(false)
const prepareError = ref('')
const actionError = ref('')
const readErrors = reactive({ state: '', profiles: '', config: '' })
const isRestoring = ref(false)
const prepareSubmitting = ref(false)
const useCustomRounds = ref(true)
const customMaxRounds = ref(10)

let pollTimer = null
let revision = 0
let disposed = false
let lastLoggedMessage = ''
let lastLoggedProfileCount = 0
const activeStates = new Set(['preparing', 'processing', 'pending', 'prerun', 'queued'])
const initialStates = new Set(['created', 'initialized'])
const savedReadyStates = new Set(['ready', 'running', 'stopping', 'paused', 'stopped', 'completed'])

const autoGeneratedRounds = computed(() => {
  const time = simulationConfig.value?.time_config
  const hours = Number(time?.total_simulation_hours)
  const minutes = Number(time?.minutes_per_round)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours <= 0 || minutes <= 0) return null
  return Math.max(1, Math.floor((hours * 60) / minutes))
})
const recommendedRounds = computed(() => Math.min(10, autoGeneratedRounds.value || 10))
const roundsValid = computed(() => Number.isInteger(customMaxRounds.value) && customMaxRounds.value >= 1 && customMaxRounds.value <= autoGeneratedRounds.value)
const roundsSliderPercent = computed(() => {
  if (!autoGeneratedRounds.value || autoGeneratedRounds.value <= 1) return 0
  return Math.max(0, Math.min(100, ((Number(customMaxRounds.value) - 1) / (autoGeneratedRounds.value - 1)) * 100 || 0))
})
const normalizeRounds = () => {
  const value = Number(customMaxRounds.value)
  customMaxRounds.value = Number.isFinite(value) && value >= 1
    ? Math.min(autoGeneratedRounds.value || 10, Math.floor(value))
    : recommendedRounds.value
}
watch(autoGeneratedRounds, (rounds) => {
  if (rounds && customMaxRounds.value > rounds) customMaxRounds.value = rounds
})

const connectionWarning = computed(() => Object.values(readErrors).filter(Boolean).join(' '))
const configIssue = computed(() => {
  const config = simulationConfig.value
  if (!config) return '尚未读到完整的环境配置。'
  if (!autoGeneratedRounds.value) return '环境中的时间配置不完整。'
  if (!Array.isArray(config.agent_configs) || !config.agent_configs.length) return '角色活动配置尚未齐全。'
  if (profiles.value.length < config.agent_configs.length) return '角色资料尚未全部读取完成。'
  if (!Array.isArray(config.event_config?.initial_posts) || !Array.isArray(config.event_config?.hot_topics)) return '初始事件配置尚未齐全。'
  if (currentSimulation.value?.enable_twitter !== false && !config.twitter_config) return 'Twitter 平台配置尚未齐全。'
  if (currentSimulation.value?.enable_reddit !== false && !config.reddit_config) return 'Reddit 平台配置尚未齐全。'
  return ''
})
const canStartSimulation = computed(() => preparationReady.value && !configIssue.value && !prepareError.value && !actionError.value && !connectionWarning.value && !isRestoring.value && !prepareSubmitting.value && (!useCustomRounds.value || roundsValid.value))
const canRetryPrepare = computed(() => !!prepareError.value || preparationStatus.value === 'created')
const preparationTitle = computed(() => {
  if (prepareSubmitting.value) return '正在提交环境准备'
  if (prepareError.value) return '环境准备未完成'
  if (actionError.value) return '暂时无法开始准备'
  if (connectionWarning.value) return '连接暂时中断'
  if (preparationReady.value && !configIssue.value) return '环境已就绪，可以选择推演轮数'
  if (preparationReady.value) return '正在核对已保存的准备结果'
  if (preparationStatus.value === 'created') return '环境尚未开始准备'
  if (preparationStatus.value === 'preparing') return phase.value >= 3 ? '正在完成环境准备' : phase.value >= 2 ? '正在生成双平台配置' : '正在生成角色资料'
  return '正在读取已保存的准备状态'
})
const preparationDescription = computed(() => {
  if (prepareSubmitting.value) return '这一步需要读取图谱并准备角色，请稍候。离开或刷新页面后，可重新打开这条记录查看进度。'
  if (prepareError.value) return '已有资料已保留，可以先恢复查看，或明确重试环境准备。'
  if (preparationReady.value && !configIssue.value) return '建议先进行少量轮次，验证角色表现与整体流程，再选择完整推演。'
  if (preparationReady.value) return '正在读取已有角色、时间安排与初始事件，资料齐全后将开放下一步。'
  if (preparationStatus.value === 'created') return '点击开始环境准备后，会调用当前配置的模型生成角色与推演环境。'
  if (preparationStatus.value === 'preparing') return `${prepareProgress.value === null ? '' : `已完成 ${prepareProgress.value}%。`}准备正在后台执行，本页会继续读取进度；刷新页面不会重新提交。`
  if (preparationStatus.value === 'unknown') return '暂时无法确认准备进度。请恢复查看；本页不会自动重新提交任务。'
  return '先确认已有任务和结果，再继续当前流程。'
})
const totalTopicsCount = computed(() => profiles.value.reduce((sum, profile) => sum + (profile.interested_topics?.length || 0), 0))
const stanceLabel = (stance) => ({ supportive: '支持', opposing: '反对', neutral: '中立', observer: '观察' }[stance] || stance || '未设置')
const getAgentUsername = (agentId) => profiles.value[agentId]?.username || `agent_${agentId}`
const selectProfile = (profile) => { selectedProfile.value = profile }
const addLog = (message) => { if (!disposed) emit('add-log', message) }
const logOnce = (message) => {
  if (message && message !== lastLoggedMessage) {
    lastLoggedMessage = message
    addLog(message)
  }
}
const stopPolling = () => {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}
const isCurrent = (token) => !disposed && token === revision
const unwrap = (response) => {
  if (response?.success && response.data) return response.data
  const error = new Error(response?.error || response?.message || '暂时无法读取准备状态')
  error.isServerRejection = true
  throw error
}
const handlePrepareFailure = (message) => {
  preparationReady.value = false
  preparationStatus.value = 'failed'
  prepareError.value = message || '环境准备已中断。已有资料保留在本地，请检查模型与 Zep 连接后重试。'
  phase.value = Math.max(1, Math.min(phase.value, 3))
  logOnce(`环境准备未完成：${prepareError.value}`)
  emit('update-status', 'error')
}
const updateProgress = (data) => {
  if (Number.isFinite(Number(data.progress)) && data.progress !== null && data.progress !== undefined) {
    prepareProgress.value = Math.max(0, Math.min(100, Math.round(Number(data.progress))))
  }
  if (data.task_id) taskId.value = data.task_id
  const detail = data.progress_detail
  currentStage.value = detail?.current_stage_name || detail?.current_stage || ''
  const stage = `${currentStage.value} ${data.message || ''}`
  if (/copying_scripts|准备模拟脚本|完成准备/.test(stage)) phase.value = 3
  else if (/generating_config|生成模拟配置|生成.*配置/.test(stage)) phase.value = 2
  else if (/generating_profiles|生成人设|生成.*角色|生成Agent/.test(stage)) phase.value = 1
  if (detail?.item_description) logOnce(`${detail.current_stage_name || '环境准备'}：${detail.item_description}`)
  else if (data.message) logOnce(data.message)
}

// All polling is read-only and serialized. Only an initial unprepared instance
// or the explicit retry action below can submit paid preparation work.
const readPreparedData = async (simulationId, token) => {
  const results = await Promise.allSettled([
    getSimulationProfilesRealtime(simulationId),
    getSimulationConfigRealtime(simulationId)
  ])
  if (!isCurrent(token)) return
  const [profilesResult, configResult] = results
  try {
    if (profilesResult.status === 'rejected') throw profilesResult.reason
    const data = unwrap(profilesResult.value)
    readErrors.profiles = ''
    if (Array.isArray(data.profiles) && (data.profiles.length || !data.is_generating)) profiles.value = data.profiles
    if (data.total_expected) expectedTotal.value = data.total_expected
    if (profiles.value.length !== lastLoggedProfileCount) {
      lastLoggedProfileCount = profiles.value.length
      addLog(`已读取 ${profiles.value.length}${expectedTotal.value ? ` / ${expectedTotal.value}` : ''} 位角色资料。`)
    }
  } catch {
    readErrors.profiles = '暂时无法读取角色资料。'
  }
  try {
    if (configResult.status === 'rejected') throw configResult.reason
    const data = unwrap(configResult.value)
    readErrors.config = ''
    if (data.config && typeof data.config === 'object') simulationConfig.value = data.config
    else if (preparationReady.value) simulationConfig.value = null
    if (!preparationReady.value && !prepareError.value) {
      if (data.config_generated && data.config) phase.value = 3
      else if (data.profiles_generated || data.generation_stage === 'generating_config') phase.value = 2
    }
  } catch {
    readErrors.config = '暂时无法读取环境配置。'
  }
}

const submitPreparation = async (simulationId, token) => {
  prepareSubmitting.value = true
  preparationReady.value = false
  prepareError.value = ''
  actionError.value = ''
  phase.value = 1
  prepareProgress.value = null
  taskId.value = null
  emit('update-status', 'processing')
  addLog('开始准备推演环境。')
  try {
    const data = unwrap(await prepareSimulation({
      simulation_id: simulationId,
      use_llm_for_profiles: true,
      parallel_profile_count: 5
    }))
    if (!isCurrent(token)) return false
    readErrors.state = ''
    if (data.task_id) taskId.value = data.task_id
    if (data.expected_entities_count) expectedTotal.value = data.expected_entities_count
    preparationStatus.value = 'preparing'
    logOnce(data.already_prepared ? '发现已有准备结果，正在恢复读取。' : '准备请求已接受，正在读取后台进度。')
    return true
  } catch (error) {
    if (!isCurrent(token)) return false
    if (error.response || error.isServerRejection) {
      actionError.value = error.message || '准备请求未被接受，请检查连接配置后重试。'
      logOnce(actionError.value)
    } else {
      // A lost response does not prove the server rejected or failed the task.
      readErrors.state = '尚未确认准备请求的结果，正在重新读取已保存的进度。'
    }
    return true
  } finally {
    if (isCurrent(token)) prepareSubmitting.value = false
  }
}

const readPreparation = async (simulationId, token, options) => {
  const state = unwrap(await getSimulation(simulationId))
  if (!isCurrent(token)) return false
  currentSimulation.value = state
  const data = unwrap(await getPrepareStatus({ simulation_id: simulationId }))
  if (!isCurrent(token)) return false
  readErrors.state = ''
  const status = String(data.status || '').toLowerCase()
  const savedStatus = String(state.status || '').toLowerCase()
  updateProgress(data)
  const isActive = activeStates.has(status)
  const isPrepared = data.already_prepared || status === 'ready' || status === 'completed' || (savedReadyStates.has(savedStatus) && state.config_generated)

  // Ready artifacts take precedence: a later simulation run may have failed
  // even though its preparation remains valid and must not be repeated.
  if (isPrepared) {
    preparationReady.value = true
    preparationStatus.value = 'ready'
    prepareError.value = ''
    actionError.value = ''
    await readPreparedData(simulationId, token)
    if (!isCurrent(token)) return false
    if (!configIssue.value && !connectionWarning.value) {
      phase.value = 4
      prepareProgress.value = 100
      logOnce('已恢复完整的环境配置，可以选择轮数并进入推演。')
      emit('update-status', 'completed')
      return false
    }
    phase.value = 3
    emit('update-status', 'processing')
    return true
  }

  preparationReady.value = false
  if (status === 'failed' || (savedStatus === 'failed' && !isActive)) {
    handlePrepareFailure(data.error || state.error)
    if (options.manualRetry) return submitPreparation(simulationId, token)
    await readPreparedData(simulationId, token)
    return !!connectionWarning.value
  }

  if (isActive || activeStates.has(savedStatus)) {
    preparationStatus.value = 'preparing'
    prepareError.value = ''
    actionError.value = ''
    phase.value = Math.max(1, Math.min(phase.value, 3))
    emit('update-status', 'processing')
    await readPreparedData(simulationId, token)
    return true
  }

  if (initialStates.has(savedStatus) && (!status || status === 'not_started' || initialStates.has(status))) {
    preparationStatus.value = 'created'
    prepareError.value = ''
    phase.value = 1
    if (options.allowInitialPrepare || options.manualRetry) return submitPreparation(simulationId, token)
    return false
  }

  preparationStatus.value = 'unknown'
  phase.value = Math.max(1, Math.min(phase.value, 3))
  await readPreparedData(simulationId, token)
  return true
}

const restorePreparation = async (options = {}) => {
  if (disposed || isRestoring.value || prepareSubmitting.value || !props.simulationId) return
  stopPolling()
  const token = ++revision
  const simulationId = props.simulationId
  isRestoring.value = true
  let shouldPoll = false
  try {
    shouldPoll = await readPreparation(simulationId, token, options)
  } catch {
    if (!isCurrent(token)) return
    // Read errors never set the task to failed and never resubmit preparation.
    readErrors.state = '暂时无法读取后台进度。'
    shouldPoll = true
  } finally {
    if (isCurrent(token)) {
      isRestoring.value = false
      if (shouldPoll) pollTimer = setTimeout(() => restorePreparation(), 3000)
    }
  }
}
const retryPreparation = () => restorePreparation({ manualRetry: true })
const handleStartSimulation = () => {
  if (!canStartSimulation.value) return
  const params = useCustomRounds.value ? { maxRounds: customMaxRounds.value } : {}
  addLog(`准备进入推演，共 ${useCustomRounds.value ? customMaxRounds.value : autoGeneratedRounds.value} 轮。`)
  emit('next-step', params)
}

const logContent = ref(null)
watch(() => props.systemLogs?.length, () => {
  nextTick(() => {
    if (logContent.value) logContent.value.scrollTop = logContent.value.scrollHeight
  })
})
watch(() => props.simulationId, (simulationId) => {
  stopPolling()
  revision += 1
  isRestoring.value = false
  prepareSubmitting.value = false
  preparationReady.value = false
  preparationStatus.value = 'loading'
  phase.value = 0
  taskId.value = null
  prepareProgress.value = null
  currentStage.value = ''
  profiles.value = []
  expectedTotal.value = null
  simulationConfig.value = null
  currentSimulation.value = null
  selectedProfile.value = null
  prepareError.value = ''
  actionError.value = ''
  Object.keys(readErrors).forEach((key) => { readErrors[key] = '' })
  customMaxRounds.value = 10
  useCustomRounds.value = true
  lastLoggedMessage = ''
  lastLoggedProfileCount = 0
  if (simulationId) restorePreparation({ allowInitialPrepare: true })
  else actionError.value = '尚未找到推演记录，请返回图谱页面继续。'
}, { immediate: true })
onUnmounted(() => {
  disposed = true
  revision += 1
  stopPolling()
})
</script>

<style scoped>
.preparation-state {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 20px;
  border: 1px solid #c9ddd4;
  border-radius: 12px;
  background: #f0f7f3;
  color: #173c31;
}
.preparation-state.has-error {
  border-color: #edc8bd;
  background: #fff5f1;
  color: #813820;
}
.preparation-state.has-warning {
  border-color: #e1d1a7;
  background: #fffaf0;
  color: #75571e;
}
.preparation-eyebrow { font-size: 12px; font-weight: 600; }
.preparation-state h3 { margin: 5px 0 8px; font-size: 17px; line-height: 1.5; }
.preparation-state p { margin: 5px 0 0; font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.connection-warning { font-weight: 500; }
.preparation-actions { display: flex; flex-shrink: 0; flex-wrap: wrap; gap: 8px; }
.preparation-btn {
  min-height: 40px;
  padding: 9px 13px;
  border: 1px solid #147d64;
  border-radius: 8px;
  background: #147d64;
  color: white;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.preparation-btn.secondary { background: white; color: #20654f; border-color: #bdd1c7; }
.preparation-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.badge.error { color: #9c3d25; background: #ffe8e1; }
.rounds-number { width: 100px; min-height: 44px; border: 1px solid #c9d6d0; border-radius: 6px; padding: 4px 8px; background: white; }
.rounds-number[aria-invalid="true"] { border-color: #b2573d; }
.rounds-error { margin: 12px 0 0; color: #9c3d25; font-size: 13px; }
button:focus-visible, input:focus-visible { outline: 3px solid #358c72; outline-offset: 3px; }
.highlight-tip { border: 0; background: transparent; padding: 0; font: inherit; text-align: left; }
@media (max-width: 700px) {
  .preparation-state { flex-direction: column; }
  .preparation-actions { width: 100%; }
  .rounds-header { gap: 16px; align-items: flex-start; flex-wrap: wrap; }
  .slider-display { gap: 12px; flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
  .rounds-content, .switch-track, .switch-track::after { animation: none !important; transition: none !important; }
}
.env-setup-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.scroll-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Step Card */
.step-card {
  background: #FFF;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  border: 1px solid #EAEAEA;
  transition: all 0.3s ease;
  position: relative;
}

.step-card.active {
  border-color: #FF5722;
  box-shadow: 0 4px 12px rgba(255, 87, 34, 0.08);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.step-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 20px;
  font-weight: 700;
  color: #E0E0E0;
}

.step-card.active .step-num,
.step-card.completed .step-num {
  color: #000;
}

.step-title {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.5px;
}

.badge {
  font-size: 10px;
  padding: 4px 8px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
}

.badge.success { background: #E8F5E9; color: #2E7D32; }
.badge.processing { background: #FF5722; color: #FFF; }
.badge.pending { background: #F5F5F5; color: #999; }
.badge.accent { background: #E3F2FD; color: #1565C0; }

.card-content {
  /* No extra padding - uses step-card's padding */
}

.api-note {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #999;
  margin-bottom: 8px;
}

.description {
  font-size: 12px;
  color: #666;
  line-height: 1.5;
  margin-bottom: 16px;
}

/* Action Section */
.action-section {
  margin-top: 16px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn.primary {
  background: #000;
  color: #FFF;
}

.action-btn.primary:hover:not(:disabled) {
  opacity: 0.8;
}

.action-btn.secondary {
  background: #F5F5F5;
  color: #333;
}

.action-btn.secondary:hover:not(:disabled) {
  background: #E5E5E5;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.action-group {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.action-group.dual {
  display: grid;
  grid-template-columns: 1fr 1fr;
}

.action-group.dual .action-btn {
  width: 100%;
}

/* Info Card */
.info-card {
  background: #F5F5F5;
  border-radius: 6px;
  padding: 16px;
  margin-top: 16px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px dashed #E0E0E0;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 12px;
  color: #666;
}

.info-value {
  font-size: 13px;
  font-weight: 500;
}

.info-value.mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
  background: #F9F9F9;
  padding: 16px;
  border-radius: 6px;
}

.stat-card {
  text-align: center;
}

.stat-value {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #000;
  font-family: 'JetBrains Mono', monospace;
}

.stat-label {
  font-size: 9px;
  color: #999;
  text-transform: uppercase;
  margin-top: 4px;
  display: block;
}

/* Profiles Preview */
.profiles-preview {
  margin-top: 20px;
  border-top: 1px solid #E5E5E5;
  padding-top: 16px;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.preview-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.profiles-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-height: 320px;
  overflow-y: auto;
  padding-right: 4px;
}

.profiles-list::-webkit-scrollbar {
  width: 4px;
}

.profiles-list::-webkit-scrollbar-thumb {
  background: #DDD;
  border-radius: 2px;
}

.profiles-list::-webkit-scrollbar-thumb:hover {
  background: #CCC;
}

.profile-card {
  background: #FAFAFA;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.profile-card:hover {
  border-color: #999;
  background: #FFF;
}

.profile-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.profile-realname {
  font-size: 14px;
  font-weight: 700;
  color: #000;
}

.profile-username {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #999;
}

.profile-meta {
  margin-bottom: 8px;
}

.profile-profession {
  font-size: 11px;
  color: #666;
  background: #F0F0F0;
  padding: 2px 8px;
  border-radius: 3px;
}

.profile-bio {
  font-size: 12px;
  color: #444;
  line-height: 1.6;
  margin: 0 0 10px 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.profile-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.topic-tag {
  font-size: 10px;
  color: #1565C0;
  background: #E3F2FD;
  padding: 2px 8px;
  border-radius: 10px;
}

.topic-more {
  font-size: 10px;
  color: #999;
  padding: 2px 6px;
}

/* Config Preview */
/* Config Detail Panel */
.config-detail-panel {
  margin-top: 16px;
}

.config-block {
  margin-top: 16px;
  border-top: 1px solid #E5E5E5;
  padding-top: 12px;
}

.config-block:first-child {
  margin-top: 0;
  border-top: none;
  padding-top: 0;
}

.config-block-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.config-block-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.config-block-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: #F1F5F9;
  color: #475569;
  padding: 2px 8px;
  border-radius: 10px;
}

/* Config Grid */
.config-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.config-item {
  background: #F9F9F9;
  padding: 12px 14px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-item-label {
  font-size: 11px;
  color: #94A3B8;
}

.config-item-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  font-weight: 600;
  color: #1E293B;
}

/* Time Periods */
.time-periods {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.period-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #F9F9F9;
  border-radius: 6px;
}

.period-label {
  font-size: 12px;
  font-weight: 500;
  color: #64748B;
  min-width: 70px;
}

.period-hours {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #475569;
  flex: 1;
}

.period-multiplier {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  color: #6366F1;
  background: #EEF2FF;
  padding: 2px 6px;
  border-radius: 4px;
}

/* Agents Cards */
.agents-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}

.agents-cards::-webkit-scrollbar {
  width: 4px;
}

.agents-cards::-webkit-scrollbar-thumb {
  background: #DDD;
  border-radius: 2px;
}

.agents-cards::-webkit-scrollbar-thumb:hover {
  background: #CCC;
}

.agent-card {
  background: #F9F9F9;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 14px;
  transition: all 0.2s ease;
}

.agent-card:hover {
  border-color: #999;
  background: #FFF;
}

/* Agent Card Header */
.agent-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid #F1F5F9;
}

.agent-identity {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.agent-id {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #94A3B8;
}

.agent-name {
  font-size: 14px;
  font-weight: 600;
  color: #1E293B;
}

.agent-tags {
  display: flex;
  gap: 6px;
}

.agent-type {
  font-size: 10px;
  color: #64748B;
  background: #F1F5F9;
  padding: 2px 8px;
  border-radius: 4px;
}

.agent-stance {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 4px;
}

.stance-neutral {
  background: #F1F5F9;
  color: #64748B;
}

.stance-supportive {
  background: #DCFCE7;
  color: #16A34A;
}

.stance-opposing {
  background: #FEE2E2;
  color: #DC2626;
}

.stance-observer {
  background: #FEF3C7;
  color: #D97706;
}

/* Agent Timeline */
.agent-timeline {
  margin-bottom: 14px;
}

.timeline-label {
  display: block;
  font-size: 10px;
  color: #94A3B8;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.mini-timeline {
  display: flex;
  gap: 2px;
  height: 16px;
  background: #F8FAFC;
  border-radius: 4px;
  padding: 3px;
}

.timeline-hour {
  flex: 1;
  background: #E2E8F0;
  border-radius: 2px;
  transition: all 0.2s;
}

.timeline-hour.active {
  background: linear-gradient(180deg, #6366F1, #818CF8);
}

.timeline-marks {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: #94A3B8;
}

/* Agent Params */
.agent-params {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.param-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.param-item .param-label {
  font-size: 10px;
  color: #94A3B8;
}

.param-item .param-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.param-value.with-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mini-bar {
  height: 4px;
  background: linear-gradient(90deg, #6366F1, #A855F7);
  border-radius: 2px;
  min-width: 4px;
  max-width: 40px;
}

.param-value.positive {
  color: #16A34A;
}

.param-value.negative {
  color: #DC2626;
}

.param-value.neutral {
  color: #64748B;
}

.param-value.highlight {
  color: #6366F1;
}

/* Platforms Grid */
.platforms-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.platform-card {
  background: #F9F9F9;
  padding: 14px;
  border-radius: 6px;
}

.platform-card-header {
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #E5E5E5;
}

.platform-name {
  font-size: 13px;
  font-weight: 600;
  color: #333;
}

.platform-params {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.param-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.param-label {
  font-size: 12px;
  color: #64748B;
}

.param-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #1E293B;
}

/* Reasoning Content */
.reasoning-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reasoning-item {
  padding: 12px 14px;
  background: #F9F9F9;
  border-radius: 6px;
}

.reasoning-text {
  font-size: 13px;
  color: #555;
  line-height: 1.7;
  margin: 0;
}

/* Profile Modal */
.profile-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.profile-modal {
  background: #FFF;
  border-radius: 16px;
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 24px;
  background: #FFF;
  border-bottom: 1px solid #F0F0F0;
}

.modal-header-info {
  flex: 1;
}

.modal-name-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}

.modal-realname {
  font-size: 20px;
  font-weight: 700;
  color: #000;
}

.modal-username {
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: #999;
}

.modal-profession {
  font-size: 12px;
  color: #666;
  background: #F5F5F5;
  padding: 4px 10px;
  border-radius: 4px;
  display: inline-block;
  font-weight: 500;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  color: #999;
  border-radius: 50%;
  font-size: 24px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  transition: color 0.2s;
  padding: 0;
}

.close-btn:hover {
  color: #333;
}

.modal-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

/* 基本信息网格 */
.modal-info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px 16px;
  margin-bottom: 32px;
  padding: 0;
  background: transparent;
  border-radius: 0;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 11px;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.info-value {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}

.info-value.mbti {
  font-family: 'JetBrains Mono', monospace;
  color: #FF5722;
}

/* 模块区域 */
.modal-section {
  margin-bottom: 28px;
}

.section-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.section-bio {
  font-size: 14px;
  color: #333;
  line-height: 1.6;
  margin: 0;
  padding: 16px;
  background: #F9F9F9;
  border-radius: 6px;
  border-left: 3px solid #E0E0E0;
}

/* 话题标签 */
.topics-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.topic-item {
  font-size: 11px;
  color: #1565C0;
  background: #E3F2FD;
  padding: 4px 10px;
  border-radius: 12px;
  transition: all 0.2s;
  border: none;
}

.topic-item:hover {
  background: #BBDEFB;
  color: #0D47A1;
}

/* 详细人设 */
.persona-dimensions {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.dimension-card {
  background: #F8F9FA;
  padding: 12px;
  border-radius: 6px;
  border-left: 3px solid #DDD;
  transition: all 0.2s;
}

.dimension-card:hover {
  background: #F0F0F0;
  border-left-color: #999;
}

.dim-title {
  display: block;
  font-size: 12px;
  font-weight: 700;
  color: #333;
  margin-bottom: 4px;
}

.dim-desc {
  display: block;
  font-size: 10px;
  color: #888;
  line-height: 1.4;
}

.persona-content {
  max-height: none;
  overflow: visible;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

.persona-content::-webkit-scrollbar {
  width: 4px;
}

.persona-content::-webkit-scrollbar-thumb {
  background: #DDD;
  border-radius: 2px;
}

.section-persona {
  font-size: 13px;
  color: #555;
  line-height: 1.8;
  margin: 0;
  text-align: justify;
}

/* System Logs */
.system-logs {
  background: #000;
  color: #DDD;
  padding: 16px;
  font-family: 'JetBrains Mono', monospace;
  border-top: 1px solid #222;
  flex-shrink: 0;
}

.log-header {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #333;
  padding-bottom: 8px;
  margin-bottom: 8px;
  font-size: 10px;
  color: #888;
}

.log-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 80px; /* Approx 4 lines visible */
  overflow-y: auto;
  padding-right: 4px;
}

.log-content::-webkit-scrollbar {
  width: 4px;
}

.log-content::-webkit-scrollbar-thumb {
  background: #333;
  border-radius: 2px;
}

.log-line {
  font-size: 11px;
  display: flex;
  gap: 12px;
  line-height: 1.5;
}

.log-time {
  color: #666;
  min-width: 75px;
}

.log-msg {
  color: #CCC;
  word-break: break-all;
}

/* Spinner */
.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid #E5E5E5;
  border-top-color: #FF5722;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
/* Orchestration Content */
.orchestration-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-top: 16px;
}

.box-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.narrative-box {
  background: #FFFFFF;
  padding: 20px 24px;
  border-radius: 12px;
  border: 1px solid #EEF2F6;
  box-shadow: 0 4px 24px rgba(0,0,0,0.03);
  transition: all 0.3s ease;
}

.narrative-box .box-label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #666;
  font-size: 13px;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
  font-weight: 600;
}

.special-icon {
  filter: drop-shadow(0 2px 4px rgba(255, 87, 34, 0.2));
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.narrative-box:hover .special-icon {
  transform: rotate(180deg);
}

.narrative-text {
  font-family: 'Inter', 'Noto Sans SC', system-ui, sans-serif;
  font-size: 14px;
  color: #334155;
  line-height: 1.8;
  margin: 0;
  text-align: justify;
  letter-spacing: 0.01em;
}

.topics-section {
  background: #FFF;
}

.hot-topics-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hot-topic-tag {
  font-size: 12px;
  color:rgba(255, 86, 34, 0.88);
  background: #FFF3E0;
  padding: 4px 10px;
  border-radius: 12px;
  font-weight: 500;
}

.hot-topic-more {
  font-size: 11px;
  color: #999;
  padding: 4px 6px;
}

.initial-posts-section {
  border-top: 1px solid #EAEAEA;
  padding-top: 16px;
}

.posts-timeline {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-left: 8px;
  border-left: 2px solid #F0F0F0;
  margin-top: 12px;
}

.timeline-item {
  position: relative;
  padding-left: 20px;
}

.timeline-marker {
  position: absolute;
  left: 0;
  top: 14px;
  width: 12px;
  height: 2px;
  background: #DDD;
}

.timeline-content {
  background: #F9F9F9;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #EEE;
}

.post-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.post-role {
  font-size: 11px;
  font-weight: 700;
  color: #333;
  text-transform: uppercase;
}

.post-agent-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.post-id,
.post-username {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #666;
  line-height: 1;
  vertical-align: baseline;
}

.post-username {
  margin-right: 6px;
}

.post-text {
  font-size: 12px;
  color: #555;
  line-height: 1.5;
  margin: 0;
}

/* 模拟轮数配置样式 */
.rounds-config-section {
  margin: 24px 0;
  padding-top: 24px;
  border-top: 1px solid #EAEAEA;
}

.rounds-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1E293B;
}

.section-desc {
  font-size: 12px;
  color: #94A3B8;
}

.desc-highlight {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: #1E293B;
  background: #F1F5F9;
  padding: 1px 6px;
  border-radius: 4px;
  margin: 0 2px;
}

/* Switch Control */
.switch-control {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px 4px 4px;
  border-radius: 20px;
  min-height: 44px;
  border: 0;
  background: transparent;
  font: inherit;
  flex-shrink: 0;
  transition: background 0.2s;
}

.switch-control:hover {
  background: #F8FAFC;
}

.switch-track {
  width: 36px;
  height: 20px;
  background: #E2E8F0;
  border-radius: 10px;
  position: relative;
  transition: all 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.switch-track::after {
  content: '';
  position: absolute;
  left: 2px;
  top: 2px;
  width: 16px;
  height: 16px;
  background: #FFF;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  transition: transform 0.3s cubic-bezier(0.4, 0.0, 0.2, 1);
}

.switch-control.checked .switch-track {
  background: #147d64;
}

.switch-control.checked .switch-track::after {
  transform: translateX(16px);
}

.switch-label {
  font-size: 12px;
  font-weight: 500;
  color: #64748B;
}

.switch-control.checked .switch-label {
  color: #1E293B;
}

/* Slider Content */
.rounds-content {
  animation: fadeIn 0.3s ease;
}

.slider-display {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 16px;
}

.slider-main-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.val-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 24px;
  font-weight: 700;
  color: #000;
}

.val-unit {
  font-size: 12px;
  color: #666;
  font-weight: 500;
}

.slider-meta-info {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #64748B;
  background: #F1F5F9;
  padding: 4px 8px;
  border-radius: 4px;
}

.range-wrapper {
  position: relative;
  padding: 0 2px;
}

.minimal-slider {
  -webkit-appearance: none;
  width: 100%;
  height: 4px;
  background: #E2E8F0;
  border-radius: 2px;
  outline: none;
  background-image: linear-gradient(#000, #000);
  background-size: var(--percent, 0%) 100%;
  background-repeat: no-repeat;
  cursor: pointer;
}

.minimal-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #FFF;
  border: 2px solid #000;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0,0,0,0.1);
  transition: transform 0.1s;
  margin-top: -6px; /* Center thumb */
}

.minimal-slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.minimal-slider::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 2px;
}

.range-marks {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #94A3B8;
  position: relative;
}

.mark-recommend {
  cursor: pointer;
  min-height: 32px;
  margin-top: -8px;
  padding: 6px;
  border: 0;
  background: transparent;
  color: #356955;
  font: inherit;
  transition: color 0.2s;
  position: relative;
}

.mark-recommend:hover {
  color: #000;
}

.mark-recommend.active {
  color: #000;
  font-weight: 600;
}

/* Auto Info */
.auto-info-card {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #F8FAFC;
  padding: 16px 20px;
  border-radius: 8px;
}

.auto-value {
  display: flex;
  flex-direction: row;
  align-items: baseline;
  gap: 4px;
  padding-right: 24px;
  border-right: 1px solid #E2E8F0;
}

.auto-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  justify-content: center;
}

.auto-meta-row {
  display: flex;
  align-items: center;
}

.duration-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 500;
  color: #64748B;
  background: #FFFFFF;
  border: 1px solid #E2E8F0;
  padding: 3px 8px;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.auto-desc {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.auto-desc p {
  margin: 0;
  font-size: 13px;
  color: #64748B;
  line-height: 1.5;
}

.highlight-tip {
  margin-top: 4px !important;
  font-size: 12px !important;
  color: #000 !important;
  font-weight: 500;
  cursor: pointer;
}

.highlight-tip:hover {
  text-decoration: underline;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Modal Transition */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .profile-modal {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.modal-leave-active .profile-modal {
  transition: all 0.3s ease-in;
}

.modal-enter-from .profile-modal,
.modal-leave-to .profile-modal {
  transform: scale(0.95) translateY(10px);
  opacity: 0;
}
</style>
