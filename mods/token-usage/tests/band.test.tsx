import { expect, test } from 'claude-code/testing'

const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 }, view: {} },
  viewport: { columns: 100, rows: 40 },
}

test('band folds to one row and unfolds into details', async ($, on) => {
  const now = Date.UTC(2026, 9, 6, 10)
  on('clock.now', () => ({ value: now }))
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: { model: 'opus[1m]', effortLevel: 'high' } }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 84_000, window: 200_000, percent: 42 }, rateLimits: [{ kind: 'five_hour', percentUsed: 56, resetsAt: '2026-10-06T12:00:00Z' }] } }))
  on('command.run', () => ({ text: '' }))
  // The engine's own band, empty here: ours stacks above it.
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  await $.session.measure({
    context: { tokens: 84_000, window: 200_000, percent: 42 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 56, resetsAt: '2026-10-06T12:00:00Z' }],
    changed: ['context', 'rateLimits'],
  })

  const folded = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await folded.find({ type: 'Text', text: /42%/ })).toBeDefined()
  expect(await folded.find({ type: 'Text', text: /↻/ })).toBeUndefined()
  expect(await folded.find({ type: 'Text', text: /cache hit/ })).toBeUndefined()
  await folded.unmount()

  await $.command.run({
    command: 'token-usage',
    args: 'open',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 100 },
  } as Parameters<typeof $.command.run>[0])
  const open = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await open.find({ type: 'Text', text: /cache hit/ })).toBeDefined()
  expect(await open.find({ type: 'Text', text: /main/ })).toBeDefined()
  await open.unmount()
})

test('main model and effort show before any request, from settings', async ($, on) => {
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('command.run', () => ({ text: '' }))
  on('settings.read', () => ({ value: { model: 'claude-opus-5-5[1m]', effortLevel: 'high' } }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 84_000, window: 200_000, percent: 42 }, rateLimits: [] } }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  await $.command.run({
    command: 'token-usage',
    args: 'close',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 100 },
  } as Parameters<typeof $.command.run>[0])
  const ui = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await ui.find({ type: 'Text', text: /Opus 5\.5/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /high/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /█/ })).toBeDefined()
  await ui.unmount()
})
