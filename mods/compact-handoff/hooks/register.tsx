import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionMessage } from 'claude-code'

import type { Handoff, Summary } from '../types'

import { applyThemeArgs, palette, parseTheme, PRESETS, themePath } from './theme'
import type { ThemeFile } from './theme'

export type { Handoff }

const TAG = '[compact-handoff]'
const KEEP_PROMPTS = 4
const KEEP_FILES = 15

// What the summarizer is asked to keep, on top of the engine's own prompt.
export const INSTRUCTIONS = [
  'Keep for the continuation, precisely:',
  "1. The user's original request and every later change to it, in their own words.",
  '2. The task list with each item done / in progress / not started.',
  '3. Decisions already made and constraints the user set (do not re-ask them).',
  '4. Files created or edited and why; commands that failed and the cause.',
  '5. The exact next step that was about to happen.',
].join('\n')

const clip = (s: string, n: number) => {
  const t = s.trim().replace(/\s+\n/g, '\n')
  return t.length > n ? `${t.slice(0, n)}…` : t
}

// The engine's compaction summary opens the continued conversation as a user message.
const SUMMARY_START = /^(This session is being continued|<compact|Summary of the conversation)/i

const isTypedPrompt = (m: SessionMessage) =>
  m.role === 'user' &&
  m.text.trim() !== '' &&
  !(m.toolResults?.length) &&
  !m.text.startsWith(TAG) &&
  !SUMMARY_START.test(m.text.trimStart()) &&
  !m.text.trimStart().startsWith('<')

const STATUS_OF: Record<string, string> = { '[x]': 'completed', '[>]': 'in_progress', '[ ]': 'pending' }

// Reads a note `render` wrote back into its parts, so a second compaction keeps the first one's.
export const parseNote = (note: string): Handoff => {
  const hand: Handoff = { prompts: [], tasks: [], files: [], failures: [], lastStep: '' }
  let section = ''
  const last: string[] = []
  for (const line of note.split('\n')) {
    if (line.startsWith('## ')) {
      section = line.slice(3)
      continue
    }
    if (section.startsWith("User's requests")) {
      const m = /^\d+\. (.*)$/.exec(line)
      if (m?.[1]) hand.prompts.push(m[1])
    } else if (section === 'Task list') {
      const m = /^(\[[x> ]\]) (.*)$/.exec(line)
      if (m?.[1] && m[2]) hand.tasks.push({ subject: m[2], status: STATUS_OF[m[1]] ?? 'pending' })
    } else if (section === 'Files touched' && line.startsWith('- ')) hand.files.push(line.slice(2))
    else if (section === 'Recent failed commands' && line.startsWith('- ')) hand.failures.push(line.slice(2))
    else if (section.startsWith('Last assistant message') && !line.startsWith('Next: ')) last.push(line)
  }
  hand.lastStep = last.join('\n').trim()
  return hand
}

// What the earlier note held comes first; what happened since is laid over it.
export const mergeHandoff = (before: Handoff, now: Handoff): Handoff => {
  const prompts = [...before.prompts, ...now.prompts.filter(p => !before.prompts.includes(p))]
  const bySubject = new Map(before.tasks.map(t => [t.subject, t]))
  for (const t of now.tasks) bySubject.set(t.subject, t)
  return {
    prompts: prompts.length > KEEP_PROMPTS ? [prompts[0] ?? '', ...prompts.slice(-(KEEP_PROMPTS - 1))] : prompts,
    tasks: [...bySubject.values()],
    files: [...new Set([...before.files, ...now.files])].slice(-KEEP_FILES),
    failures: (now.failures.length ? now.failures : before.failures).slice(-3),
    lastStep: now.lastStep || before.lastStep,
  }
}

// Everything here is read from the transcript itself, so it survives reloads.
export const collect = (messages: readonly SessionMessage[]): Handoff => {
  const earlier = [...messages].reverse().find(m => m.role === 'user' && m.text.startsWith(TAG))
  const fresh = collectFresh(messages)
  return earlier ? mergeHandoff(parseNote(earlier.text), fresh) : fresh
}

const collectFresh = (messages: readonly SessionMessage[]): Handoff => {
  const typed = messages.filter(isTypedPrompt).map(m => clip(m.text, 300))
  const prompts = typed.length > KEEP_PROMPTS ? [typed[0] ?? '', ...typed.slice(-(KEEP_PROMPTS - 1))] : typed

  const tasks = new Map<string, { subject: string; status: string }>()
  let todos: { subject: string; status: string }[] | null = null
  const files = new Set<string>()
  const failures: string[] = []

  for (const m of messages) {
    for (const use of m.toolUses) {
      const input = use.input
      if (use.tool === 'TaskCreate') {
        const task = (use.result as { task?: { id?: string } } | undefined)?.task
        tasks.set(task?.id ?? use.tool_use_id, { subject: String(input.subject ?? ''), status: 'pending' })
      } else if (use.tool === 'TaskUpdate') {
        const found = tasks.get(String(input.taskId))
        if (found) {
          if (typeof input.status === 'string') found.status = input.status
          if (typeof input.subject === 'string') found.subject = input.subject
        }
      } else if (use.tool === 'TodoWrite' && Array.isArray(input.todos)) {
        todos = (input.todos as { content?: string; status?: string }[]).map(t => ({
          subject: String(t.content ?? ''),
          status: String(t.status ?? 'pending'),
        }))
      } else if (['Edit', 'Write', 'NotebookEdit'].includes(use.tool)) {
        const path = input.file_path ?? input.notebook_path
        if (typeof path === 'string') files.add(path)
      } else if (use.tool === 'Bash' && use.isError) {
        failures.push(`${clip(String(input.command ?? ''), 160)} → ${clip(use.text ?? '', 200)}`)
      }
    }
  }

  const last = [...messages].reverse().find(m => m.role === 'assistant' && m.text.trim() !== '')
  return {
    prompts,
    tasks: (todos ?? [...tasks.values()]).filter(t => t.status !== 'deleted'),
    files: [...files].slice(-KEEP_FILES),
    failures: failures.slice(-3),
    lastStep: last ? clip(last.text, 400) : '',
  }
}

const MARK: Record<string, string> = { completed: '[x]', in_progress: '[>]', pending: '[ ]' }

export const render = (hand: Handoff, cwd: string): string => {
  const out = [
    `${TAG} Handoff note written just before compaction, from the transcript itself.`,
    'Use it with the summary above to continue the same task without asking the user to repeat anything.',
  ]
  if (cwd) out.push(`Working directory: ${cwd}`)
  if (hand.prompts.length) {
    out.push('', "## User's requests (verbatim, oldest first)")
    hand.prompts.forEach((p, i) => out.push(`${i + 1}. ${p}`))
  }
  if (hand.tasks.length) {
    out.push('', '## Task list')
    hand.tasks.forEach(t => out.push(`${MARK[t.status] ?? '[ ]'} ${t.subject}`))
  }
  if (hand.files.length) out.push('', '## Files touched', ...hand.files.map(f => `- ${f}`))
  if (hand.failures.length) out.push('', '## Recent failed commands', ...hand.failures.map(f => `- ${f}`))
  if (hand.lastStep) out.push('', '## Last assistant message before compaction', hand.lastStep)
  out.push('', 'Next: pick up from the first unfinished task (or the last message) and continue.')
  return out.join('\n')
}

const TRACKED = ['TaskCreate', 'TaskUpdate', 'TodoWrite', 'Edit', 'Write', 'NotebookEdit', 'Agent']

const EMPTY: Summary = {
  handoff: { prompts: [], tasks: [], files: [], failures: [], lastStep: '' },
  agents: [],
  updatedAt: 0,
  isBandHidden: false,
  cwd: '',
  isExpanded: false,
  theme: { preset: 'default', overrides: {} },
}

const summary = atom({ plugin: 'compact-handoff', key: 'summary' } as const, EMPTY)

export const progress = (tasks: Handoff['tasks']) => {
  const live = tasks.filter(t => t.status !== 'deleted')
  return { done: live.filter(t => t.status === 'completed').length, total: live.length, current: live.find(t => t.status === 'in_progress') }
}

export const bar = (done: number, total: number, width: number): string => {
  const n = total ? Math.round((done / total) * width) : 0
  return '█'.repeat(n) + '·'.repeat(width - n)
}

export const shortPath = (path: string, cwd: string): string =>
  cwd && path.startsWith(`${cwd}/`) ? path.slice(cwd.length + 1) : path.replace(/^\/Users\/[^/]+/, '~')

const oneLine = (s: string, n: number) => {
  const t = s.replace(/\s+/g, ' ').trim()
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

async function loadTheme($: EngineInterface): Promise<ThemeFile> {
  return parseTheme(await $.fs.read(themePath(await $.env.get('HOME'), await $.env.get('CLAUDE_MODS_THEME_FILE'))).catch(() => ''))
}

const THEME_HELP: Record<string, string> = {
  default: 'the terminal theme colors as they are',
  colorblind: 'colors that stay distinct with color blindness (Okabe-Ito)',
  ocean: 'teal and blue, suited to dark backgrounds',
  vivid: 'bright primary colors',
}

// `theme` alone opens a keyboard picker; otherwise the words go to applyThemeArgs.
async function themeCommand($: EngineInterface, words: string[]): Promise<string> {
  if (words[0] === 'theme' && !words[1]) {
    const names = Object.keys(PRESETS)
    const picked = await $.ui
      .ask('Which color theme?', { header: 'Theme', options: names.map(n => `${n} — ${THEME_HELP[n] ?? ''}`) })
      .catch(() => '')
    const name = names.find(n => picked.startsWith(n))
    if (!name) return 'Theme unchanged.'
    words = ['theme', name]
  }
  const r = applyThemeArgs(await loadTheme($), words)
  if (r.next) {
    const theme = r.next
    await $.fs.write(themePath(await $.env.get('HOME'), await $.env.get('CLAUDE_MODS_THEME_FILE')), `${JSON.stringify(theme, null, 2)}\n`).catch(() => undefined)
    await update($, summary, s => ({ ...s, theme }))
  }
  return r.text
}

async function refreshSummary($: EngineInterface) {
  const [messages, roster, cwd, theme] = await Promise.all([
    $.session.messages(),
    $.agent.list().catch(() => []),
    $.session.cwd().catch(() => ''),
    loadTheme($),
  ])
  const now = await $.clock.now()
  await update($, summary, s => ({
    ...s,
    handoff: collect(messages),
    agents: roster
      .filter(a => ['pending', 'running', 'waiting'].includes(a.status))
      .map(a => ({ type: a.type, description: a.description, status: a.status })),
    updatedAt: now,
    cwd,
    theme,
  }))
}

async function setOption($: EngineInterface, field: string, value: boolean): Promise<boolean> {
  const r = await $.config.set({ key: `compact-handoff.${field}`, value }).catch(() => ({ deny: 'error' }))
  return !('deny' in r && r.deny !== undefined)
}

// Settings come from /config (userConfig); a change there reloads the module.
export const register: Register = (on, options) => {
  const isBandOn = options.band !== false
  let isHandoffOn = options.handoff !== false

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'handoff',
      description: 'Show the handoff note left at compaction (preview: the note a compact now would leave, on|off: turn on/off)',
      argumentHint: '[preview|on|off]',
    })
    await $.command.register({
      name: 'work',
      description: 'Expand/collapse the task summary above the prompt (tasks, requests, files, failed checks)',
      argumentHint: '[open|close|band on|off|theme [name]|color <slot> <#hex>]',
    })
    const started = await next(e)
    await refreshSummary($)
    return started
  })

  on('command.run', { command: 'handoff' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg === 'on' || arg === 'off') {
      if (!(await setOption($, 'handoff', arg === 'on'))) isHandoffOn = arg === 'on'
      return { text: arg === 'off' ? 'Handoff note off: compaction runs the default way.' : 'Handoff note on.' }
    }
    if (arg === 'preview') {
      const cwd = await $.session.cwd().catch(() => '')
      return { text: render(collect(await $.session.messages()), cwd) }
    }
    const saved = (await $.store.get('last')) as { at: string; note: string } | undefined
    return { text: saved ? `Last handoff note (${saved.at}):\n\n${saved.note}` : 'No compaction yet. /handoff preview shows what would be kept.' }
  })

  on('command.run', { command: 'work' }, async ($, e) => {
    const arg = e.args.trim()
    const words = arg.split(/\s+/)
    if (words[0] === 'theme' || words[0] === 'color') return { text: await themeCommand($, words) }
    if (arg === 'band off' || arg === 'band on') {
      if (!(await setOption($, 'band', arg === 'band on'))) await update($, summary, s => ({ ...s, isBandHidden: arg === 'band off' }))
      return { text: arg === 'band off' ? 'Task line hidden.' : 'Task line shown.' }
    }
    if (arg === 'close' || arg === 'open' || arg === '') {
      await refreshSummary($)
      const isExpanded = arg === 'open' || (arg === '' && !(await read($, summary)).isExpanded)
      await update($, summary, s => ({ ...s, isExpanded, isBandHidden: false }))
      return { text: isExpanded ? 'Task summary expanded. Run /work again to collapse.' : 'Task summary collapsed.' }
    }
    return { text: 'Usage: /work (expand/collapse), /work band on|off, /work theme' }
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (e.agentId === undefined) await refreshSummary($)
    return done
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (TRACKED.includes(e.tool)) await refreshSummary($)
    return ran
  }).catch(($, e, next) => next(e))

  // ------------------------------------------------------------ band

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const s = await read($, summary)
    const hand = s.handoff
    const below = await next(e)
    const { done, total, current } = progress(hand.tasks)
    const latest = hand.prompts.at(-1)
    // Collapsed, the band shows task progress only; the last request is in /work.
    if (e.props.hasSurvey || s.isBandHidden || (!isBandOn && !s.isExpanded) || (!total && (!latest || !s.isExpanded))) return below

    const { Box, Text } = $.ui.resolve(e)
    const P = palette(s.theme as ThemeFile)
    const cols = e.viewport?.columns ?? 80
    const inner = Math.max(20, cols - 6)
    const isAllDone = total > 0 && done === total
    const next1 = hand.tasks.find(t => t.status === 'pending')

    const summaryRow = total ? (
      <Text>
        <Text color={current ? P.warn : isAllDone ? P.ok : P.cache}>{current ? '▶' : isAllDone ? '✓' : '○'} </Text>
        <Text dimColor>{done}/{total} </Text>
        <Text>{oneLine(current?.subject ?? next1?.subject ?? 'all tasks done', Math.max(20, cols - 20))}</Text>
        {hand.failures.length > 0 && <Text color={P.danger}> ✗{hand.failures.length}</Text>}
      </Text>
    ) : (
      <Text>
        <Text color={P.accent}>💬 </Text>
        <Text>{oneLine(latest ?? '', Math.max(20, cols - 10))}</Text>
      </Text>
    )

    if (!s.isExpanded) {
      return (
        <Box flexDirection="column">
          {summaryRow}
          {below}
        </Box>
      )
    }

    const shown = hand.tasks.length > 8 ? [...hand.tasks.filter(t => t.status !== 'completed'), ...hand.tasks.filter(t => t.status === 'completed').slice(-2)].slice(0, 8) : hand.tasks
    const files = hand.files.slice(-3).reverse()

    return (
      <Box flexDirection="column">
        {summaryRow}
        <Box borderStyle="round" borderColor={P.cache} paddingX={1} flexDirection="column">
          {total > 0 && (
            <Text bold color={P.accent}>
              ✅ tasks {done}/{total} <Text color={P.ok}>{bar(done, total, 16)}</Text>
            </Text>
          )}
          {shown.map(t =>
            t.status === 'completed' ? (
              <Text dimColor>
                <Text color={P.ok}>✔</Text> {oneLine(t.subject, inner - 2)}
              </Text>
            ) : t.status === 'in_progress' ? (
              <Text bold>
                <Text color={P.warn}>▶</Text> {oneLine(t.subject, inner - 2)}
              </Text>
            ) : (
              <Text>
                <Text color={P.cache}>○</Text> {oneLine(t.subject, inner - 2)}
              </Text>
            ),
          )}
          {hand.tasks.length > shown.length && <Text dimColor>  +{hand.tasks.length - shown.length} more</Text>}
          {latest && (
            <Text>
              <Text color={P.accent}>💬 </Text>
              <Text dimColor>recent request </Text>
              {oneLine(latest, inner - 12)}
            </Text>
          )}
          {files.length > 0 && (
            <Text>
              <Text color={P.input}>📝 </Text>
              <Text dimColor>files {hand.files.length} </Text>
              {oneLine(files.map(f => shortPath(f, s.cwd)).join(' · '), inner - 12)}
            </Text>
          )}
          {hand.failures.map(f => (
            <Text>
              <Text color={P.danger}>✗ </Text>
              {oneLine(f, inner - 3)}
            </Text>
          ))}
          {s.agents.map(a => (
            <Text>
              <Text color={P.warn}>◐ </Text>
              <Text bold>{a.type}</Text>
              <Text dimColor> · {oneLine(a.description, Math.max(10, inner - 20))}</Text>
            </Text>
          ))}
        </Box>
        {below}
      </Box>
    )
  })

  on('session.compact', async ($, e, next) => {
    // Main conversation only; a precompute is kept for later and would go stale.
    if (e.agentId !== undefined || e.trigger === 'precompute') return next(e)
    if (!isHandoffOn) return next(e)

    const handoff = collect(e.messages)
    const cwd = await $.session.cwd().catch(() => '')
    const note = render(handoff, cwd)
    const instructions = e.instructions ? `${e.instructions}\n\n${INSTRUCTIONS}` : INSTRUCTIONS

    const done = await next({ ...e, instructions })
    if (done.skip !== undefined) return done

    // Pin the note right after the summary, ahead of the kept messages.
    const pinned: SessionMessage = { role: 'user', text: note, toolUses: [] }
    const [summary, ...kept] = done.messages
    const messages = summary ? [summary, pinned, ...kept] : [pinned]

    const at = await $.clock.now().catch(() => 0)
    await $.store.set('last', { at: at ? new Date(at).toISOString() : '', note })
    $.ui.toast(
      `📌 Handoff note pinned after compact: requests ${handoff.prompts.length} · tasks ${handoff.tasks.length} · files ${handoff.files.length} (/handoff)`,
      { timeoutMs: 6000 },
    )
    return { ...done, messages }
  }).catch(($, e, next) => next(e))
}
