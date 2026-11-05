import { expect, test } from 'claude-code/testing'

import { crossed, duration, failSummary, prefsFrom } from '../hooks/register'

test('durations read in Korean units', async () => {
  expect(duration(4_200)).toBe('4s')
  expect(duration(120_000)).toBe('2m')
  expect(duration(133_000)).toBe('2m 13s')
})

test('picks the runner summary line', async () => {
  const out = 'tests/a.py F.\nFAILED tests/a.py::x\n==== 1 failed, 12 passed in 0.4s ===='
  expect(failSummary(out)).toBe('1 failed, 12 passed in 0.4s')
  expect(failSummary('all good')).toBeUndefined()
})

test('alerts once per upward crossing', async () => {
  expect(crossed(50, 62, [60, 85])).toBe(60)
  expect(crossed(62, 70, [60, 85])).toBeUndefined()
  expect(crossed(50, 90, [60, 85])).toBe(85)
  expect(crossed(90, 20, [60, 85])).toBeUndefined()
})

test('/task-alert writes the sound row of /config', async ($, on) => {
  const set: [string, unknown][] = []
  on('config.set', (_$, e) => (set.push([e.key, e.value]), { value: e.value }))
  on('command.run', () => ({ text: '' }))
  const run = (args: string) =>
    $.command.run({
      command: 'task-alert',
      args,
      origin: { kind: 'composer' },
      presentation: { isFullscreen: false, columns: 100 },
    } as Parameters<typeof $.command.run>[0])
  expect((await run('off')).text).toMatch(/sound off/)
  expect(set.at(-1)).toEqual(['work-alerts.sound', false])
  expect((await run('on')).text).toMatch(/sound on/)
  expect(set.at(-1)).toEqual(['work-alerts.sound', true])
})

test('options map to prefs, with safe defaults', async () => {
  expect(prefsFrom({})).toEqual({ isOn: true, hasSound: true, hasDesktop: true, longTurnSec: 60, subagent: 'popup only' })
  expect(prefsFrom({ sound: false, longTurn: '2m', subagent: 'off' })).toMatchObject({ hasSound: false, longTurnSec: 120, subagent: 'off' })
})
