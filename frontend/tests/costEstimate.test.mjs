import test from 'node:test'
import assert from 'node:assert/strict'
import { estimateSimulationCost, describeEstimate, totalRoundsOf, REPORT_REQUESTS } from '../src/utils/costEstimate.js'

const agents = (count, extra = {}) => Array.from({ length: count }, (_, i) => ({
  agent_id: i, activity_level: 1, active_hours: Array.from({ length: 24 }, (_, h) => h), ...extra
}))
const flatTime = (extra = {}) => ({
  total_simulation_hours: 24, minutes_per_round: 60, agents_per_hour_min: 2, agents_per_hour_max: 2,
  peak_hours: [], off_peak_hours: [], ...extra
})

test('a fully deterministic scenario is counted exactly', () => {
  // 3 rounds x min(2 targeted, 5 available) = 6 actions per platform.
  const estimate = estimateSimulationCost({ time_config: flatTime(), agent_configs: agents(5) }, { rounds: 3, platforms: 2 })
  assert.equal(estimate.rounds, 3)
  assert.equal(estimate.agents, 5)
  assert.equal(estimate.activePerRound.expected, 2)
  assert.deepEqual(estimate.requests, { low: 12, expected: 18, high: 24 })
})

test('a run cannot be longer than the generated time configuration', () => {
  const config = { time_config: flatTime({ total_simulation_hours: 4 }), agent_configs: agents(3) }
  assert.equal(totalRoundsOf(config), 4)
  assert.equal(estimateSimulationCost(config, { rounds: 99 }).rounds, 4)
  assert.equal(estimateSimulationCost(config).rounds, 4)
  assert.equal(estimateSimulationCost(config, { rounds: 0 }).rounds, 4)
})

test('fewer candidates than the target caps the activity', () => {
  const config = { time_config: flatTime({ agents_per_hour_min: 10, agents_per_hour_max: 10 }), agent_configs: agents(3) }
  assert.equal(estimateSimulationCost(config, { rounds: 5, platforms: 1 }).activePerRound.expected, 3)
})

test('agents that are never awake or never act produce no requests', () => {
  const asleep = estimateSimulationCost({ time_config: flatTime(), agent_configs: agents(4, { active_hours: [] }) }, { rounds: 5 })
  assert.deepEqual(asleep.requests, { low: 0, expected: 0, high: 0 })
  const idle = estimateSimulationCost({ time_config: flatTime(), agent_configs: agents(4, { activity_level: 0 }) }, { rounds: 5 })
  assert.equal(idle.requests.expected, 0)
})

test('off-peak hours scale the target down and peak hours scale it up', () => {
  const time = flatTime({ agents_per_hour_min: 10, agents_per_hour_max: 10, peak_hours: [1], off_peak_hours: [0] })
  const config = { time_config: time, agent_configs: agents(100) }
  // hour 0: floor(10 * 0.3) = 3, hour 1: floor(10 * 1.5) = 15
  assert.equal(estimateSimulationCost(config, { rounds: 1, platforms: 1 }).activePerRound.expected, 3)
  const two = estimateSimulationCost(config, { rounds: 2, platforms: 1 })
  assert.equal(two.activePerRound.expected, (3 + 15) / 2)
})

test('partial activity levels use the exact expectation, not the mean', () => {
  // One agent awake with probability 0.5 and a target of 1: it acts half the time.
  const config = { time_config: flatTime({ agents_per_hour_min: 1, agents_per_hour_max: 1 }), agent_configs: agents(1, { activity_level: 0.5 }) }
  assert.equal(estimateSimulationCost(config, { rounds: 1, platforms: 1 }).activePerRound.expected, 0.5)
})

test('missing fields fall back to the same defaults as the simulation script', () => {
  const estimate = estimateSimulationCost({ time_config: { total_simulation_hours: 2, minutes_per_round: 60 }, agent_configs: [{ agent_id: 0 }] }, { rounds: 2, platforms: 1 })
  // Default active hours are 8-22 and activity 0.5: hours 0 and 1 are asleep.
  assert.equal(estimate.requests.expected, 0)
})

test('nothing is estimated without agents or a usable time configuration', () => {
  assert.equal(estimateSimulationCost(null), null)
  assert.equal(estimateSimulationCost({ time_config: flatTime(), agent_configs: [] }), null)
  assert.equal(estimateSimulationCost({ time_config: { total_simulation_hours: 0 }, agent_configs: agents(2) }), null)
  assert.equal(estimateSimulationCost({ time_config: flatTime(), agent_configs: agents(2) }, { platforms: 0 }), null)
})

test('the description states the range, the report and that it is only an estimate', () => {
  const text = describeEstimate(estimateSimulationCost({ time_config: flatTime(), agent_configs: agents(5) }, { rounds: 3, platforms: 2 }))
  assert.match(text, /3 轮 × 2 个平台/)
  assert.match(text, /12–24 次模型请求/)
  assert.ok(text.includes(`${REPORT_REQUESTS.low}–${REPORT_REQUESTS.high}`))
  assert.match(text, /粗略估算/)
  assert.equal(describeEstimate(null), '')
})
