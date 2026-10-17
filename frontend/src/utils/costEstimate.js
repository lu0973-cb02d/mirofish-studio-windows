// A rough, offline estimate of how many model requests a simulation will make.
//
// It mirrors backend/scripts/run_parallel_simulation.py::get_active_agents_for_round:
// per round the hour of day picks a peak / off-peak multiplier, a target of
// uniform(min, max) * multiplier agents is drawn, and only agents whose
// active_hours contain that hour and who pass an activity_level coin flip are
// candidates. Every selected agent takes one LLM action per platform. The
// expected value is computed exactly; low and high are the extremes of the
// uniform draw and bound where a single run is likely to land.
//
// What the estimate cannot know is how many requests one action costs: an
// agent that calls a tool may need a second request. That range is stated, not
// hidden, and the report below is a typical span, not a measurement.

export const REQUESTS_PER_ACTION = { low: 1, expected: 1.5, high: 2 }
export const REPORT_REQUESTS = { low: 25, high: 60 }

// Same fallbacks the simulation script applies to missing fields.
const DEFAULT_PEAK_HOURS = [9, 10, 11, 14, 15, 20, 21, 22]
const DEFAULT_OFF_PEAK_HOURS = [0, 1, 2, 3, 4, 5]
const DEFAULT_ACTIVE_HOURS = Array.from({ length: 15 }, (_, i) => 8 + i)

const number = (value, fallback) => (Number.isFinite(Number(value)) && value !== null && value !== '' ? Number(value) : fallback)

export function totalRoundsOf(config) {
  const time = config?.time_config || {}
  const hours = number(time.total_simulation_hours, 72)
  const minutes = number(time.minutes_per_round, 30)
  if (hours <= 0 || minutes <= 0) return 0
  return Math.floor((hours * 60) / minutes)
}

/**
 * @param {object} config simulation_config.json contents
 * @param {{rounds?: number, platforms?: number}} options
 * @returns {null | {rounds, platforms, agents, activePerRound, requests, report}}
 */
export function estimateSimulationCost(config, { rounds, platforms = 2 } = {}) {
  const agentConfigs = Array.isArray(config?.agent_configs) ? config.agent_configs : []
  const available = totalRoundsOf(config)
  if (!agentConfigs.length || !available || platforms < 1) return null

  const time = config.time_config || {}
  const minutesPerRound = number(time.minutes_per_round, 30)
  const baseMin = number(time.agents_per_hour_min, 5)
  const baseMax = number(time.agents_per_hour_max, 20)
  const peak = new Set(Array.isArray(time.peak_hours) ? time.peak_hours : DEFAULT_PEAK_HOURS)
  const offPeak = new Set(Array.isArray(time.off_peak_hours) ? time.off_peak_hours : DEFAULT_OFF_PEAK_HOURS)
  const peakMultiplier = number(time.peak_activity_multiplier, 1.5)
  const offPeakMultiplier = number(time.off_peak_activity_multiplier, 0.3)

  const roundCount = Math.min(available, Number.isInteger(rounds) && rounds > 0 ? rounds : available)

  // Distribution of how many agents are awake and pass their activity coin
  // flip at an hour: a sum of independent Bernoulli trials (Poisson binomial).
  const candidateCache = new Map()
  const candidatesAt = (hour) => {
    if (candidateCache.has(hour)) return candidateCache.get(hour)
    let pmf = [1]
    for (const agent of agentConfigs) {
      const hours = Array.isArray(agent.active_hours) ? agent.active_hours : DEFAULT_ACTIVE_HOURS
      if (!hours.includes(hour)) continue
      const p = Math.min(1, Math.max(0, number(agent.activity_level, 0.5)))
      const next = new Array(pmf.length + 1).fill(0)
      pmf.forEach((mass, k) => { next[k] += mass * (1 - p); next[k + 1] += mass * p })
      pmf = next
    }
    const mean = pmf.reduce((sum, mass, k) => sum + mass * k, 0)
    const value = { pmf, mean }
    candidateCache.set(hour, value)
    return value
  }
  // E[min(floor(U * multiplier), K)] for U ~ Uniform(baseMin, baseMax) and K the
  // candidate count, integrated over U with a midpoint rule.
  const STEPS = 48
  const expectedActive = (pmf, multiplier) => {
    let total = 0
    for (let step = 0; step < STEPS; step += 1) {
      const target = Math.floor((baseMin + ((step + 0.5) / STEPS) * (baseMax - baseMin)) * multiplier)
      total += pmf.reduce((sum, mass, k) => sum + mass * Math.min(target, k), 0)
    }
    return total / STEPS
  }

  const totals = { low: 0, expected: 0, high: 0 }
  for (let round = 0; round < roundCount; round += 1) {
    const hour = Math.floor((round * minutesPerRound) / 60) % 24
    const multiplier = peak.has(hour) ? peakMultiplier : offPeak.has(hour) ? offPeakMultiplier : 1
    const { pmf, mean } = candidatesAt(hour)
    totals.low += Math.min(Math.floor(baseMin * multiplier), mean)
    totals.expected += expectedActive(pmf, multiplier)
    totals.high += Math.min(Math.floor(baseMax * multiplier), mean)
  }

  const activePerRound = {
    low: totals.low / roundCount, expected: totals.expected / roundCount, high: totals.high / roundCount
  }
  const requests = {
    low: Math.round(totals.low * platforms * REQUESTS_PER_ACTION.low),
    expected: Math.round(totals.expected * platforms * REQUESTS_PER_ACTION.expected),
    high: Math.round(totals.high * platforms * REQUESTS_PER_ACTION.high)
  }
  return { rounds: roundCount, platforms, agents: agentConfigs.length, activePerRound, requests, report: REPORT_REQUESTS }
}

export function describeEstimate(estimate) {
  if (!estimate) return ''
  const { requests, report, rounds, platforms } = estimate
  return `${rounds} 轮 × ${platforms} 个平台，预计约 ${requests.low}–${requests.high} 次模型请求` +
    `（常见约 ${requests.expected}）；之后生成报告通常再需要 ${report.low}–${report.high} 次。这是粗略估算，实际以服务商账单为准。`
}
