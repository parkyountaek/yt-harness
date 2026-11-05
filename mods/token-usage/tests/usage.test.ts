import { expect, test } from 'claude-code/testing'

import {
  agentTag,
  nested,
  addAgentRun,
  addMainTurn,
  agentModels,
  contextState,
  fineBar,
  fmt,
  limitLabel,
  resetsIn,
  modelName,
  stack,
  windowFor,
} from '../hooks/register'
import { applyThemeArgs, palette, PRESETS } from '../hooks/theme'
import type { Usage } from '../types'

const EMPTY: Usage = {
  main: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, turns: 0 },
  model: null,
  turns: [],
  agents: [],
  context: null,
  isBandHidden: false,
}

const turn = (model: string) => ({
  input_tokens: 10,
  output_tokens: 5,
  cache_read_input_tokens: 100,
  cache_creation_input_tokens: 20,
  model,
})

test('formats token counts', async () => {
  expect(fmt(950)).toBe('950')
  expect(fmt(1_234)).toBe('1.2k')
  expect(fmt(84_400)).toBe('84k')
  expect(fmt(1_250_000)).toBe('1.25M')
})

test('shortens model ids', async () => {
  expect(modelName('claude-opus-5-5[1m]')).toBe('Opus 5.5 1M')
  expect(modelName('claude-haiku-4-5-20251001')).toBe('Haiku 4.5')
  expect(modelName('claude-fable-5-1')).toBe('Fable 5.1')
  expect(modelName('gpt-x')).toBe('gpt-x')
})

test('bars and charts keep a fixed width', async () => {
  expect(fineBar(0, 8)).toBe('········')
  expect(fineBar(50, 8)).toBe('████····')
  expect(fineBar(100, 8)).toBe('████████')
  expect(stack([900, 50, 1], 10, 1000)).toEqual([9, 1, 1])
})

test('context state pairs icon and label with color', async () => {
  expect(contextState(10).label).toBe('ok')
  expect(contextState(70).tone).toBe('warn')
  expect(contextState(90).icon).toBe('●')
})

test('main turns and subagent runs are counted apart', async () => {
  let u = addMainTurn(EMPTY, turn('claude-opus-5-5'))
  u = addAgentRun(u, 'a1', turn('claude-haiku-4-5'))
  u = addAgentRun(u, 'a1', turn('claude-haiku-4-5'))
  expect(u.main).toEqual({ input: 10, output: 5, cacheRead: 100, cacheWrite: 20, turns: 1 })
  expect(u.model).toBe('claude-opus-5-5')
  expect(u.agents.length).toBe(1)
  expect(u.agents[0]?.runs).toBe(2)
  expect(u.agents[0]?.output).toBe(10)
  expect(u.agents[0]?.model).toBe('claude-haiku-4-5')
})

test('rate-limit labels and reset times', async () => {
  const now = Date.parse('2026-10-06T10:00:00Z')
  expect(limitLabel('five_hour')).toBe('5h')
  expect(limitLabel('seven_day')).toBe('7d')
  expect(resetsIn('2026-10-06T12:00:00Z', now)).toBe('↻2h')
  expect(resetsIn('2026-10-06T10:20:00Z', now)).toBe('↻20m')
  expect(resetsIn('2026-10-09T14:00:00Z', now)).toBe('↻3d 4h')
  expect(resetsIn('2026-10-09T10:00:00Z', now)).toBe('↻3d')
  expect(resetsIn(undefined, now)).toBe('')
})

test('themes resolve presets and overrides', async () => {
  expect(palette({ preset: 'default', overrides: {} }).danger).toBe('error')
  expect(palette({ preset: 'colorblind', overrides: { output: '#123456' } }).output).toBe('#123456')
  expect(palette({ preset: 'nope', overrides: {} }).ok).toBe(PRESETS.default?.ok)
})

test('theme commands change preset and slots', async () => {
  const base = { preset: 'default', overrides: {} }
  expect(applyThemeArgs(base, ['theme', 'ocean']).next?.preset).toBe('ocean')
  expect(applyThemeArgs(base, ['theme', 'nope']).next).toBeUndefined()
  expect(applyThemeArgs(base, ['color', 'output', '#FF8800']).next?.overrides).toEqual({ output: '#FF8800' })
  expect(applyThemeArgs(base, ['color', 'output', 'not a color']).next).toBeUndefined()
})

test('subagent windows and model chips', async () => {
  const main = { ...EMPTY, model: 'claude-opus-5-5[1m]', context: { window: 1_000_000, tokens: 1, percent: 0 } }
  expect(windowFor('claude-opus-5-5[1m]', main)).toBe(1_000_000)
  expect(windowFor('claude-haiku-4-5', main)).toBe(200_000)
  let u = addAgentRun(main, 'a', turn('claude-haiku-4-5'))
  u = addAgentRun(u, 'b', turn('claude-haiku-4-5'))
  u = { ...u, agents: u.agents.map(a => ({ ...a, status: 'running' })) }
  expect(agentModels(u.agents)).toEqual([['Haiku 4.5', 2, undefined]])
})

test('subagents get distinct numbers and colors', () => {
  expect(agentTag(0).mark).toBe('①')
  expect(agentTag(1).mark).toBe('②')
  expect(agentTag(0).tone).not.toBe(agentTag(1).tone)
  expect(agentTag(20).mark).toBe('(21)')
})

test('spawned subagents sit under the one that spawned them', () => {
  const row = (id: string, parentId?: string) => ({ id, parentId, type: 'x', description: id, model: '', status: 'running', runs: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0 })
  const out = nested([row('a'), row('b'), row('c', 'a'), row('d', 'c'), row('e', 'gone')])
  expect(out.map(o => `${o.a.id}${o.depth}`)).toEqual(['a0', 'c1', 'd2', 'b0', 'e0'])
})
