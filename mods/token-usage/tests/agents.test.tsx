import { expect, test } from 'claude-code/testing'

import { elapsed } from '../hooks/register'

const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: true, maxRows: 30, bodyColumns: 120, scroll: { offset: 0, bodyRows: 30 }, view: {} },
  viewport: { columns: 120, rows: 40 },
}

test('a running subagent gets its own row; pressing it opens its transcript', async ($, on) => {
  let isUp = false
  const opened: string[] = []
  on('agent.list', () => ({ value: ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'].map(id => ({ id, type: 'Explore', description: `job ${id}`, status: 'running' as const })) }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('command.run', () => ({ text: '' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.panes', () => ({ value: isUp ? [{ id: 'agent-view', title: '', isShown: true, isFocused: false, isPlaced: true, plugin: 'token-usage' }] : [] }))
  on('ui.open', (_$, e) => ((isUp = true), opened.push(e.title ?? ''), { value: { isPlaced: true } }))
  on('ui.close', () => ((isUp = false), { value: undefined }))
  on('session.messages', () => ({
    value: [
      { role: 'user', text: 'Count the tests', toolUses: [] },
      { role: 'assistant', text: 'Looking at the tests folder', toolUses: [{ tool_use_id: 't1', tool: 'Read', input: { file_path: '/repo/tests/test_cli.py' }, result: 'x', text: '535 lines' }] },
    ],
  }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })

  await $.tool.call({ tool: 'Read', file_path: '/repo/tests/test_cli.py', agentId: 'a1' } as Parameters<typeof $.tool.call>[0])

  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await band.find({ type: 'Text', text: /①/ })).toBeDefined()
  expect(await band.find({ type: 'Text', text: /Read tests\/test_cli\.py/ })).toBeDefined()
  expect(await band.find({ type: 'Text', text: /ctx/ })).toBeDefined()
  await band.press({ key: 'agent:a1' })
  expect(opened).toHaveLength(1)
  await band.unmount()

  const again = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await again.find({ type: 'Text', text: /👁/ })).toBeDefined()
  await again.unmount()

  const pane = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', component: 'Pane', requestId: 'agent-view', props: {}, viewport: { columns: 60, rows: 20 } } as Parameters<typeof $.ui.mount>[0])
  expect(await pane.find({ type: 'Text', text: /Looking at the tests folder/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /⎿/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /Esc: back to main/ })).toBeDefined()
  await pane.unmount()
})

test('past five subagents, "more" opens a list where any one can be picked', async ($, on) => {
  let isUp = false
  on('agent.list', () => ({ value: ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'].map(id => ({ id, type: 'Explore', description: `job ${id}`, status: 'running' as const })) }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('command.run', () => ({ text: '' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.panes', () => ({ value: isUp ? [{ id: 'agent-view', title: '', isShown: true, isFocused: false, isPlaced: true, plugin: 'token-usage' }] : [] }))
  on('ui.open', () => ((isUp = true), { value: { isPlaced: true } }))
  on('ui.close', () => ((isUp = false), { value: undefined }))
  on('session.messages', () => ({ value: [{ role: 'assistant', text: 'seventh at work', toolUses: [] }] }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  for (let i = 1; i <= 7; i++) {
    await $.tool.call({ tool: 'Read', file_path: `/repo/f${i}.py`, agentId: `a${i}` } as Parameters<typeof $.tool.call>[0])
  }

  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await band.find({ type: 'Text', text: /⑥/ })).toBeUndefined()
  await band.press({ key: 'agent:more' })
  await band.unmount()

  const PANE = { plugin: 'token-usage', surface: 'terminal', component: 'Pane', requestId: 'agent-view', props: { bodyColumns: 100 }, viewport: { columns: 100, rows: 30 } }
  const list = await $.ui.mount(PANE as Parameters<typeof $.ui.mount>[0])
  expect(await list.find({ type: 'Text', text: /⑦/ })).toBeDefined()
  await list.press({ key: 'pick:a7' })
  await list.unmount()

  const one = await $.ui.mount(PANE as Parameters<typeof $.ui.mount>[0])
  expect(await one.find({ type: 'Text', text: /seventh at work/ })).toBeDefined()
  await one.unmount()
})

test('a viewed subagent that finishes keeps its row and pane, marked done', async ($, on) => {
  let isUp = false
  const toasts: string[] = []
  on('agent.list', () => ({ value: [{ id: 'a1', type: 'Explore', description: 'job a1', status: 'running' as const }] }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', (_$, e) => (toasts.push(e.text), { value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('command.run', () => ({ text: '' }))
  on('tool.call', () => ({ result: 'ok' }))
    on('ui.panes', () => ({ value: isUp ? [{ id: 'agent-view', title: '', isShown: true, isFocused: false, isPlaced: true, plugin: 'token-usage' }] : [] }))
  on('ui.open', () => ((isUp = true), { value: { isPlaced: true } }))
  on('ui.close', () => ((isUp = false), { value: undefined }))
  on('session.messages', () => ({ value: [{ role: 'assistant', text: 'final answer', toolUses: [] }] }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  await $.tool.call({ tool: 'Read', file_path: '/repo/a.py', agentId: 'a1' } as Parameters<typeof $.tool.call>[0])
  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  await band.press({ key: 'agent:a1' })
  await band.unmount()

  await $.turn.complete({ agentId: 'a1', answer: 'final answer' } as Parameters<typeof $.turn.complete>[0])
  expect(toasts.some(t => /done/.test(t))).toBe(true)

  const after = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await after.find({ type: 'Text', text: /✓ done/ })).toBeDefined()
  await after.unmount()
  const pane = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', component: 'Pane', requestId: 'agent-view', props: { bodyColumns: 100 }, viewport: { columns: 100, rows: 30 } } as Parameters<typeof $.ui.mount>[0])
  expect(await pane.find({ type: 'Text', text: /Done/ })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /final answer/ })).toBeDefined()
  await pane.unmount()
})

test('ids the roster never lists (engine forks) get no row', async ($, on) => {
  on('agent.list', () => ({ value: [] }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  await $.tool.call({ tool: 'Read', file_path: '/repo/a.py', agentId: 'fork-1' } as Parameters<typeof $.tool.call>[0])
  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await band.find({ type: 'Text', text: /①/ })).toBeUndefined()
  await band.unmount()
})

test('a failed run says so, with its elapsed time; closing the pane clears the view', async ($, on) => {
  let now = Date.UTC(2026, 9, 6, 10)
  on('agent.list', () => ({ value: [{ id: 'a1', type: 'Explore', description: 'job a1', status: 'running' as const }] }))
  on('clock.now', () => ({ value: now }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('session.messages', () => ({ value: [] }))
  on('turn.complete', () => ({ text: '' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  await $.tool.call({ tool: 'Read', file_path: '/repo/a.py', agentId: 'a1' } as Parameters<typeof $.tool.call>[0])
  now += 72_000
  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await band.find({ type: 'Text', text: /1m 12s/ })).toBeDefined()
  await band.press({ key: 'agent:a1' })
  await band.unmount()

  await $.turn.complete({ agentId: 'a1', answer: '', reason: 'error' } as Parameters<typeof $.turn.complete>[0])
  const after = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await after.find({ type: 'Text', text: /failed/ })).toBeDefined()
  await after.unmount()

  // Pressing the name again closes the pane, as Esc does.
  const again = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  await again.press({ key: 'agent:a1' })
  await again.unmount()
  const closed = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await closed.find({ type: 'Text', text: /👁/ })).toBeUndefined()
  expect(await closed.find({ type: 'Text', text: /failed/ })).toBeUndefined()
  await closed.unmount()
})

test('elapsed reads in Korean units', () => {
  expect(elapsed(45_000)).toBe('45s')
  expect(elapsed(72_000)).toBe('1m 12s')
  expect(elapsed(3_780_000)).toBe('1h 3m')
})

test('a subagent the roster lists a moment late still gets its row', async ($, on) => {
  let now = Date.UTC(2026, 9, 6, 10)
  let isListed = false
  on('agent.list', () => ({ value: isListed ? [{ id: 'a1', type: 'Explore', description: 'late', status: 'running' as const }] : [] }))
  on('clock.now', () => ({ value: now }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  await $.tool.call({ tool: 'Read', file_path: '/repo/a.py', agentId: 'a1' } as Parameters<typeof $.tool.call>[0])
  isListed = true
  now += 4000
  await $.tool.call({ tool: 'Read', file_path: '/repo/b.py', agentId: 'a1' } as Parameters<typeof $.tool.call>[0])
  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await band.find({ type: 'Text', text: /①/ })).toBeDefined()
  await band.unmount()
})

test('subagent rows set to off draw no rows and no "more"', { options: { agentRows: 'off' } }, async ($, on) => {
  on('agent.list', () => ({ value: ['a1', 'a2', 'a3', 'a4', 'a5', 'a6'].map(id => ({ id, type: 'Explore', description: id, status: 'running' as const })) }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('tool.call', () => ({ result: 'ok' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  for (const id of ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']) {
    await $.tool.call({ tool: 'Read', file_path: '/repo/a.py', agentId: id } as Parameters<typeof $.tool.call>[0])
  }
  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  expect(await band.find({ type: 'Text', text: /①/ })).toBeUndefined()
  expect(await band.find({ type: 'Button', key: 'agent:more' })).toBeUndefined()
  await band.unmount()
})
