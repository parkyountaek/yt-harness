import { expect, test } from 'claude-code/testing'
import type { SessionMessage } from 'claude-code'

import { bar, collect, INSTRUCTIONS, parseNote, progress, render, shortPath } from '../hooks/register'

const user = (text: string): SessionMessage => ({ role: 'user', text, toolUses: [] })
const said = (text: string, toolUses: SessionMessage['toolUses'] = []): SessionMessage => ({
  role: 'assistant',
  text,
  toolUses,
})

const TRANSCRIPT: SessionMessage[] = [
  user('I want to set up mods'),
  said('', [
    { tool_use_id: 't1', tool: 'TaskCreate', input: { subject: 'write mod' }, result: { task: { id: '1', subject: 'write mod' } } },
    { tool_use_id: 't2', tool: 'TaskCreate', input: { subject: 'run tests' }, result: { task: { id: '2', subject: 'run tests' } } },
    { tool_use_id: 't3', tool: 'TaskUpdate', input: { taskId: '1', status: 'completed' } },
    { tool_use_id: 't4', tool: 'Write', input: { file_path: '/m/register.ts', content: 'x' } },
    { tool_use_id: 't5', tool: 'Bash', input: { command: 'pytest' }, text: '1 failed', isError: true },
  ]),
  { role: 'user', text: '', toolUses: [], toolResults: [] },
  user('<command-name>/token-usage</command-name>'),
  user('add alerts too'),
  said('Next I will run the tests.'),
]

test('collects requests, tasks, files, failures and last step', async () => {
  const h = collect(TRANSCRIPT)
  expect(h.prompts).toEqual(['I want to set up mods', 'add alerts too'])
  expect(h.tasks).toEqual([
    { subject: 'write mod', status: 'completed' },
    { subject: 'run tests', status: 'pending' },
  ])
  expect(h.files).toEqual(['/m/register.ts'])
  expect(h.failures).toEqual(['pytest → 1 failed'])
  expect(h.lastStep).toBe('Next I will run the tests.')
})

test('note marks tasks and ends with the next action', async () => {
  const note = render(collect(TRANSCRIPT), '/repo')
  expect(note.startsWith('[compact-handoff]')).toBe(true)
  expect(note).toContain('[x] write mod')
  expect(note).toContain('[ ] run tests')
  expect(note).toContain('Working directory: /repo')
})

test('pins the note after the summary and adds instructions', async ($, on) => {
  let told = ''
  let stored: unknown
  on('clock.now', () => ({ value: Date.UTC(2026, 9, 6) }))
  on('store.set', (_$, e) => {
    stored = e.value
    return { value: undefined }
  })
  on('session.compact', (_$, e) => {
    told = e.instructions ?? ''
    return { messages: [said('SUMMARY'), user('kept')] }
  })
  const done = await $.session.compact({ trigger: 'auto', messages: TRANSCRIPT, instructions: 'keep the API notes' })
  expect(told).toContain('keep the API notes')
  expect(told).toContain(INSTRUCTIONS)
  expect(done.skip).toBeUndefined()
  expect(String((stored as { note?: string }).note)).toContain('[compact-handoff]')
  expect(done.messages?.map(m => m.text.slice(0, 17))).toEqual(['SUMMARY', '[compact-handoff]', 'kept'])
})

test('progress, bar and short paths for the work pane', async () => {
  const tasks = [
    { subject: 'a', status: 'completed' },
    { subject: 'b', status: 'in_progress' },
    { subject: 'c', status: 'pending' },
  ]
  const p = progress(tasks)
  expect([p.done, p.total, p.current?.subject]).toEqual([1, 3, 'b'])
  expect(bar(1, 3, 6)).toBe('██····')
  expect(shortPath('/repo/src/x.py', '/repo')).toBe('src/x.py')
  expect(shortPath('/Users/<user>/.claude/a.ts', '/repo')).toBe('~/.claude/a.ts')
})

test('a note reads back into the same parts', () => {
  const hand = collect(TRANSCRIPT)
  expect(parseNote(render(hand, '/repo'))).toEqual(hand)
})

test('a second compaction keeps what the first note held', () => {
  const first = render(collect(TRANSCRIPT), '/repo')
  const after: SessionMessage[] = [
    user('This session is being continued from a previous conversation that ran out of context. Summary: ...'),
    user(first),
    user('change the theme too'),
    said('', [{ tool_use_id: 'u1', tool: 'Edit', input: { file_path: '/m/theme.ts' } }]),
    said('Theme done; tests next.'),
  ]
  const hand = collect(after)
  expect(hand.prompts[0]).toBe('I want to set up mods')
  expect(hand.prompts).toContain('change the theme too')
  expect(hand.prompts.some(p => p.startsWith('This session'))).toBe(false)
  expect(hand.tasks.map(t => t.subject)).toEqual(['write mod', 'run tests'])
  expect(hand.files).toEqual(['/m/register.ts', '/m/theme.ts'])
  expect(hand.lastStep).toBe('Theme done; tests next.')
})
