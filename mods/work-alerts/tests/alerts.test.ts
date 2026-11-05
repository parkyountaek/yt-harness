import { expect, test } from 'claude-code/testing'

import { crossed, duration, failSummary, prefsFrom, toTell, ytAlert, ytKey } from '../hooks/register'

test('durations read in compact units', async () => {
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
  expect(prefsFrom({})).toEqual({ isOn: true, hasSound: true, hasDesktop: true, longTurnSec: 60, subagent: 'popup only', hasHarness: true })
  expect(prefsFrom({ harness: false }).hasHarness).toBe(false)
  expect(prefsFrom({ sound: false, longTurn: '2m', subagent: 'off' })).toMatchObject({ hasSound: false, longTurnSec: 120, subagent: 'off' })
})

const task = (taskId: string, need: string | null, extra: Record<string, unknown> = {}) =>
  ({ taskId, need, since: 't1', state: need === 'collect' ? 'done' : 'running', command: need ? `yt cmd ${taskId}` : null, ...extra }) as Parameters<typeof ytAlert>[0]

test('each yt-harness need becomes one alert with its yt command', () => {
  expect(ytAlert(task('a', 'question', { question: 'Count blank lines?' }))).toEqual({ text: '❓ yt a asks: Count blank lines? → yt cmd a', kind: 'warn' })
  expect(ytAlert(task('b', 'collect'))?.kind).toBe('done')
  expect(ytAlert(task('c', 'collect', { state: 'failed' }))).toEqual({ text: '✗ yt c failed → yt cmd c', kind: 'fail' })
  expect(ytAlert(task('d', 'deadline'))?.text).toMatch(/past its deadline → yt cmd d/)
  expect(ytAlert(task('e', 'ended'))?.kind).toBe('fail')
  expect(ytAlert(task('f', null))).toBeUndefined()
})

test('a need is told once; a new need of the same task is told again; gone tasks are forgotten', () => {
  const snap = (tasks: ReturnType<typeof task>[]) => ({ counts: {}, tasks })
  const first = toTell(snap([task('a', 'question'), task('b', null)]), [])
  expect(first.fresh.map(t => t.taskId)).toEqual(['a'])
  expect(toTell(snap([task('a', 'question')]), first.keep).fresh).toEqual([])
  // Answered, then asked again: a new status time makes it a new need.
  expect(toTell(snap([task('a', 'question', { since: 't2' })]), first.keep).fresh).toHaveLength(1)
  expect(toTell(snap([task('a', 'collect')]), first.keep).fresh.map(ytKey)).toEqual(['a:collect:t1'])
  expect(toTell(snap([]), first.keep).keep).toEqual([])
})

test('session start reads yt panel --json, alerts once, and records it in the shared file', async ($, on) => {
  const toasts: string[] = []
  const files = new Map<string, string>()
  const snap = { schema: 1, counts: { question: 1 }, tasks: [task('read-002', 'question', { question: 'Which file?' })] }
  on('command.register', () => ({ value: undefined }))
  on('env.get', (_$, e) => ({ value: e.name === 'HOME' ? '/h' : undefined }))
  on('clock.now', () => ({ value: 1 }))
  on('ui.toast', (_$, e) => (toasts.push(e.text), { value: undefined }))
  on('fs.read', (_$, e) => (files.has(e.path) ? { value: files.get(e.path) } : { deny: 'missing' }))
  on('fs.write', (_$, e) => (files.set(e.path, e.text), { value: undefined }))
  on('process.run', (_$, e) =>
    e.argv[1] === 'panel' ? { value: { exitCode: 0, stdout: JSON.stringify(snap), stderr: '' } } : { value: { exitCode: 0, stdout: '', stderr: '' } },
  )
  on('session.start', () => ({ cwd: '/repo' }))
  for (let i = 0; i < 2; i++) {
    await $.session.start({ cwd: '/repo' } as Parameters<typeof $.session.start>[0])
    await new Promise(r => setTimeout(r, 50))
  }
  expect(toasts.filter(t => t.includes('read-002'))).toEqual(['❓ yt read-002 asks: Which file? → yt cmd read-002'])
  expect(JSON.parse(files.get('/h/yt-local/data/alerted.json') ?? '{}')).toEqual({ told: ['read-002:question:t1'] })
})
