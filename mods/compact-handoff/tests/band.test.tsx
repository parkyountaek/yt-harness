import { expect, test } from 'claude-code/testing'
import type { SessionMessage } from 'claude-code'

const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isWorking: false, maxRows: 30, bodyColumns: 100, scroll: { offset: 0, bodyRows: 30 }, view: {} },
  viewport: { columns: 100, rows: 40 },
}

const TRANSCRIPT: SessionMessage[] = [
  { role: 'user', text: 'improve the panel design', toolUses: [] },
  {
    role: 'assistant',
    text: '',
    toolUses: [
      { tool_use_id: 't1', tool: 'TaskCreate', input: { subject: 'build the tiles' }, result: { task: { id: '1', subject: 'build the tiles' } } },
      { tool_use_id: 't2', tool: 'TaskCreate', input: { subject: 'tests' }, result: { task: { id: '2', subject: 'tests' } } },
      { tool_use_id: 't3', tool: 'TaskUpdate', input: { taskId: '1', status: 'in_progress' } },
    ],
  },
]

test('work band folds to one row and unfolds into the task list', async ($, on) => {
  on('session.messages', () => ({ value: TRANSCRIPT }))
  on('agent.list', () => ({ value: [] }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('env.get', () => ({ value: undefined }))
  on('fs.read', () => ({ value: '' }))
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6) }))
  on('command.run', () => ({ text: '' }))
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine" />
  })
  const run = (args: string) =>
    $.command.run({
      command: 'work',
      args,
      origin: { kind: 'composer' },
      presentation: { isFullscreen: false, columns: 100 },
    } as Parameters<typeof $.command.run>[0])

  await run('close')
  const folded = await $.ui.mount({ plugin: 'compact-handoff', surface: 'terminal', ...BAND })
  expect(await folded.find({ type: 'Text', text: /build the tiles/ })).toBeDefined()
  expect(await folded.find({ type: 'Text', text: /recent request/ })).toBeUndefined()
  await folded.unmount()

  await run('open')
  const open = await $.ui.mount({ plugin: 'compact-handoff', surface: 'terminal', ...BAND })
  expect(await open.find({ type: 'Text', text: /tasks 0\/2/ })).toBeDefined()
  expect(await open.find({ type: 'Text', text: /recent request/ })).toBeDefined()
  await open.unmount()
})
