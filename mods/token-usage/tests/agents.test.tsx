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

test('elapsed reads in compact units', () => {
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

test('a pane whose subagent is gone can still be closed, and /clear closes it', async ($, on) => {
  let isUp = false
  const closes: string[] = []
  let roster = [{ id: 'a1', type: 'Explore', description: 'job a1', status: 'running' as const }]
  on('agent.list', () => ({ value: roster }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('session.usage', () => ({ value: null }))
  on('tool.call', () => ({ result: 'ok' }))
  on('command.run', () => ({ text: '' }))
  on('session.end', () => ({ sessionId: 's1' }))
  on('ui.panes', () => ({ value: isUp ? [{ id: 'agent-view', title: '', isShown: true, isFocused: false, isPlaced: true, plugin: 'token-usage' }] : [] }))
  on('ui.open', () => ((isUp = true), { value: { isPlaced: true } }))
  on('ui.close', (_$, e) => ((isUp = false), closes.push(e.id), { value: undefined }))
  on('session.messages', () => ({ value: [] }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  const PANE = { plugin: 'token-usage', surface: 'terminal', component: 'Pane', requestId: 'agent-view', props: {}, viewport: { columns: 60, rows: 20 } } as Parameters<typeof $.ui.mount>[0]
  const open = async () => {
    await $.tool.call({ tool: 'Read', file_path: '/repo/a.py', agentId: 'a1' } as Parameters<typeof $.tool.call>[0])
    const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
    await band.press({ key: 'agent:a1' })
    await band.unmount()
    expect(isUp).toBe(true)
  }

  // The pane always has its own close control, so a lost focus (Esc goes elsewhere) never strands it.
  await open()
  const pane = await $.ui.mount(PANE)
  await pane.press({ key: 'tab:close' })
  await pane.unmount()
  expect(isUp).toBe(false)

  // /clear forgets every subagent: the pane showing one of them closes with it.
  await open()
  await $.session.end({ reason: 'clear' } as Parameters<typeof $.session.end>[0])
  expect(isUp).toBe(false)

  // /token-usage close closes the pane as well as collapsing the details.
  roster = [{ id: 'a1', type: 'Explore', description: 'job a1', status: 'running' as const }]
  await open()
  await $.command.run({ command: 'token-usage', args: 'close' } as Parameters<typeof $.command.run>[0])
  expect(isUp).toBe(false)
  expect(closes.every(id => id === 'agent-view')).toBe(true)
})

const SNAP = {
  schema: 1,
  counts: { running: 1, question: 1, deadline: 0, collect: 1, ended: 0 },
  tasks: [
    { taskId: 'read-002', harness: 'yt-ops', runtime: 'codex', state: 'waiting-human', since: 't1', need: 'question', question: 'Count blank lines?', command: 'yt answer read-002 "..."' },
    { taskId: 'read-003', harness: 'yt-ops', runtime: 'claude', state: 'done', since: 't2', need: 'collect', command: 'yt collect read-003' },
    { taskId: 'read-004', harness: 'yt-wiki', runtime: 'claude', state: 'running', since: 't3', need: null, command: null },
  ],
}

test('yt-harness tasks: a band row with counts opens a pane listing them, needs first', async ($, on) => {
  let isUp = false
  const runs: string[][] = []
  on('agent.list', () => ({ value: [] }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('process.run', (_$, e) => (runs.push([...e.argv]), { value: { exitCode: 0, stdout: JSON.stringify(SNAP), stderr: '' } }))
  on('ui.panes', () => ({ value: isUp ? [{ id: 'agent-view', title: '', isShown: true, isFocused: false, isPlaced: true, plugin: 'token-usage' }] : [] }))
  on('ui.open', () => ((isUp = true), { value: { isPlaced: true } }))
  on('ui.close', () => ((isUp = false), { value: undefined }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  // The first draw starts the reader; the next one shows what it read.
  const first = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  await first.unmount()
  expect(runs[0]?.[0]).toMatch(/\/yt-core\/bin\/yt$/)
  expect(runs[0]?.slice(1)).toEqual(['panel', '--json'])
  const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
  const row = await band.find({ type: 'Button', key: 'yt:open' })
  expect(row?.props.label).toBe('🧩 yt 1 waiting · 1 to collect · 1 running')
  await band.press({ key: 'yt:open' })
  await band.unmount()
  expect(isUp).toBe(true)
  const pane = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', component: 'Pane', requestId: 'agent-view', props: {}, viewport: { columns: 100, rows: 20 } } as Parameters<typeof $.ui.mount>[0])
  const texts = (await pane.findAll({ type: 'Text' })).map(t => t.text).join('\n')
  expect(texts).toMatch(/read-002 asks: Count blank lines\? → yt answer read-002/)
  expect(texts).toMatch(/read-003 done, not collected → yt collect read-003/)
  expect(texts.indexOf('read-002')).toBeLessThan(texts.indexOf('read-004'))
  await pane.press({ key: 'tab:close' })
  await pane.unmount()
  expect(isUp).toBe(false)
})

test('yt-harness tasks: no row when yt is missing or nothing is going on', async ($, on) => {
  let out = { exitCode: 1, stdout: '', stderr: 'no yt' }
  on('agent.list', () => ({ value: [] }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('process.run', () => ({ value: out }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  for (const next of [out, { exitCode: 0, stdout: JSON.stringify({ ...SNAP, counts: {}, tasks: [] }), stderr: '' }]) {
    out = next
    await (await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })).unmount()
    const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Button', key: 'yt:open' })).toBeUndefined()
    await band.unmount()
  }
})

test('yt-harness tasks set to off: yt is never run and no row is drawn', { options: { harness: false } }, async ($, on) => {
  const runs: string[] = []
  on('agent.list', () => ({ value: [] }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6, 10) }))
  on('ui.status', () => ({ value: undefined }))
  on('settings.read', () => ({ value: {} }))
  on('process.run', (_$, e) => (runs.push(e.argv.join(' ')), { value: { exitCode: 0, stdout: JSON.stringify(SNAP), stderr: '' } }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  for (let i = 0; i < 2; i++) {
    const band = await $.ui.mount({ plugin: 'token-usage', surface: 'terminal', ...BAND })
    expect(await band.find({ type: 'Button', key: 'yt:open' })).toBeUndefined()
    await band.unmount()
  }
  expect(runs.filter(r => r.includes('panel'))).toEqual([])
})
