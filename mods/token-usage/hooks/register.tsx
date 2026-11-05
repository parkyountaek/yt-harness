import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextUsage, SessionMessage, SessionRateLimit, TurnUsage } from 'claude-code'

import type { AgentRow, Context, Limit, Tokens, Usage } from '../types'

import type { Slot } from './theme'
import { applyThemeArgs, palette, parseTheme, PRESETS, SLOTS, themePath } from './theme'
import type { Palette, ThemeFile } from './theme'

const KEEP_TURNS = 200
const KEEP_AGENTS = 40

const EMPTY: Usage = {
  main: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, turns: 0 },
  model: null,
  turns: [],
  agents: [],
  context: null,
  isBandHidden: false,
}

const usage = atom({ plugin: 'token-usage', key: 'usageV3' } as const, EMPTY)

async function loadTheme($: EngineInterface): Promise<ThemeFile> {
  const path = themePath(await $.env.get('HOME'), await $.env.get('CLAUDE_MODS_THEME_FILE'))
  return parseTheme(await $.fs.read(path).catch(() => ''))
}

const THEME_HELP: Record<string, string> = {
  default: 'the terminal theme colors as they are',
  colorblind: 'colors that stay distinct with color blindness (Okabe-Ito)',
  ocean: 'teal and blue, suited to dark backgrounds',
  vivid: 'bright primary colors',
}

async function themeCommand($: EngineInterface, words: string[]): Promise<{ text: string; theme?: ThemeFile }> {
  if (words[0] === 'theme' && !words[1]) {
    // No name: let the person pick with the keyboard (arrows + Enter).
    const names = Object.keys(PRESETS)
    const picked = await $.ui
      .ask('Which color theme?', {
        header: 'Theme',
        options: names.map(n => `${n} — ${THEME_HELP[n] ?? ''}`),
      })
      .catch(() => '')
    const name = names.find(n => picked.startsWith(n))
    if (!name) return { text: 'Theme unchanged.' }
    words = ['theme', name]
  }
  const r = applyThemeArgs(await loadTheme($), words)
  if (r.next) {
    const path = themePath(await $.env.get('HOME'), await $.env.get('CLAUDE_MODS_THEME_FILE'))
    const isSaved = await $.fs.write(path, `${JSON.stringify(r.next, null, 2)}\n`).then(() => true, () => false)
    // Still applied to this session when the file cannot be written.
    if (!isSaved) return { text: `${r.text}\n(could not save the theme file ${path}; applied to this session only)`, theme: r.next }
  }
  return { text: r.text, theme: r.next }
}

// Before the first request of this load: the session's figures and the configured model.
async function freshen($: EngineInterface) {
  const [now, settings] = await Promise.all([
    $.session.usage().catch(() => null),
    $.settings.read().catch(() => ({}) as Record<string, unknown>),
  ])
  if (!now) return
  await update($, usage, u => ({
    ...u,
    context: toContext(now.context),
    limits: toLimits(now.rateLimits),
    model: u.model ?? (typeof settings.model === 'string' ? settings.model : null),
    effort: u.effort ?? (typeof settings.effortLevel === 'string' ? settings.effortLevel : undefined),
  }))
}

const themeFrom = (u: Usage): Palette => palette((u.theme as ThemeFile | undefined) ?? { preset: 'default', overrides: {} })

// ---------------------------------------------------------------- formatting

export const fmt = (n: number): string => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

// "claude-opus-5-5[1m]" -> "Opus 5.5 1M", "claude-haiku-4-5-20251001" -> "Haiku 4.5"
export const modelName = (id: string): string => {
  const wide = /\[1m\]/i.test(id) ? ' 1M' : ''
  const m = /claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?/i.exec(id)
  if (!m) return id.replace(/\[1m\]/i, '') + wide
  const family = m[1] ?? ''
  const name = family.charAt(0).toUpperCase() + family.slice(1)
  return `${name} ${m[2]}${m[3] ? `.${m[3]}` : ''}${wide}`
}

const fit = (s: string, width: number) => {
  const cells = [...s].reduce((n, ch) => n + (/[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\uff00-\uff60]/.test(ch) ? 2 : 1), 0)
  return s + ' '.repeat(Math.max(0, width - cells))
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

const inputOf = (t: Tokens) => t.input + t.cacheRead + t.cacheWrite

// ---------------------------------------------------------------- glyph charts

const EIGHTHS = '▏▎▍▌▋▊▉'

// A horizontal bar at eighth-cell resolution, padded with a faint track.
export const fineBar = (percent: number, width: number): string => {
  const eighths = Math.round((Math.max(0, Math.min(100, percent)) / 100) * width * 8)
  const full = Math.floor(eighths / 8)
  const part = eighths % 8
  return ('█'.repeat(full) + (part ? EIGHTHS[part - 1] ?? '' : '')).padEnd(width, '·')
}

// Cell counts for a stacked bar; every non-zero segment keeps at least one cell.
export const stack = (parts: readonly number[], width: number, peak: number): number[] =>
  parts.map(p => (p > 0 ? Math.max(1, Math.round((p / Math.max(1, peak)) * width)) : 0))

// ---------------------------------------------------------------- context state

// Icon, label and theme color together, so the state is never color alone.
export const contextState = (percent: number) =>
  percent >= 85
    ? { icon: '●', label: 'compact soon', tone: 'danger' as const }
    : percent >= 60
      ? { icon: '◕', label: 'watch', tone: 'warn' as const }
      : percent >= 30
        ? { icon: '◑', label: 'ok', tone: 'ok' as const }
        : { icon: '◔', label: 'ok', tone: 'ok' as const }

const toLimits = (r: readonly SessionRateLimit[]): Limit[] =>
  r.map(l => ({ kind: l.kind, percentUsed: l.percentUsed, resetsAt: l.resetsAt }))

export const limitLabel = (kind: string): string =>
  kind === 'five_hour' ? '5h' : kind === 'seven_day' ? '7d' : kind === 'spend_limit' ? 'spend' : kind

// Time until a window resets, compact: "3d 4h", "2h", "25m".
export const resetsIn = (resetsAt: string | undefined, now: number): string => {
  if (!resetsAt) return ''
  const min = Math.round((Date.parse(resetsAt) - now) / 60_000)
  if (Number.isNaN(min)) return ''
  if (min < 1) return '↻soon'
  if (min < 60) return `↻${min}m`
  const h = Math.floor(min / 60)
  if (h < 24) return `↻${h}h`
  return h % 24 ? `↻${Math.floor(h / 24)}d ${h % 24}h` : `↻${Math.floor(h / 24)}d`
}

// A subagent's window: the main one when it runs the same model, else by its id.
export const windowFor = (model: string, main: Usage): number =>
  model && model === main.model && main.context ? main.context.window : /\[1m\]|-1m\b/i.test(model) ? 1_000_000 : 200_000

// Live subagents grouped by model and effort: [["Haiku 4.5", 2, "low"], ...].
export const agentModels = (agents: readonly AgentRow[]): [string, number, string | undefined][] => {
  const groups = new Map<string, [string, number, string | undefined]>()
  for (const a of agents) {
    if (!isLive(a)) continue
    const name = a.model ? modelName(a.model) : '?'
    const key = `${name}|${a.effort ?? ''}`
    const g = groups.get(key)
    groups.set(key, g ? [name, g[1] + 1, a.effort] : [name, 1, a.effort])
  }
  return [...groups.values()]
}

type Tone = 'ok' | 'warn' | 'danger' | 'cache'

// Each subagent keeps one number and color for the whole session (its order of first appearance),
// so its row above the prompt and its row in /token-usage are easy to match.
const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
const AGENT_TONES: readonly Slot[] = ['accent', 'warn', 'ok', 'input', 'output', 'cache']
export const agentTag = (index: number): { mark: string; tone: Slot } => ({
  mark: CIRCLED[index] ?? `(${index + 1})`,
  tone: AGENT_TONES[index % AGENT_TONES.length] ?? 'accent',
})

const AGENT_ICON: Record<string, { icon: string; tone: Tone }> = {
  pending: { icon: '○', tone: 'cache' },
  running: { icon: '◐', tone: 'warn' },
  waiting: { icon: '◐', tone: 'warn' },
  idle: { icon: '◌', tone: 'cache' },
  completed: { icon: '✓', tone: 'ok' },
  failed: { icon: '✗', tone: 'danger' },
  killed: { icon: '✗', tone: 'danger' },
}

const isLive = (a: AgentRow) => ['pending', 'running', 'waiting'].includes(a.status)
// A teammate waiting for a message: still around, not working.
const isIdle = (a: AgentRow) => a.status === 'idle'
const u0Live = (u: Usage) => u.agents.some(isLive)

export const STATUS_LABEL: Record<string, string> = {
  pending: 'pending',
  running: 'running',
  waiting: 'running',
  idle: 'waiting for a message',
  completed: 'done',
  failed: 'failed',
  killed: 'stopped',
}

// 1m 12s, 45s, 1h 3m
export const elapsed = (ms: number): string => {
  const sec = Math.max(0, Math.floor(ms / 1000))
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return sec % 60 ? `${min}m ${sec % 60}s` : `${min}m`
  return min % 60 ? `${Math.floor(min / 60)}h ${min % 60}m` : `${Math.floor(min / 60)}h`
}

export const agentElapsed = (a: AgentRow, now: number): string | undefined =>
  a.startedAt === undefined ? undefined : elapsed((a.endedAt ?? now) - a.startedAt)

// Children right under their parent, each with its depth, so a spawned subagent sits
// indented below the one that spawned it.
export const nested = (rows: readonly AgentRow[]): { a: AgentRow; depth: number }[] => {
  const ids = new Set(rows.map(r => r.id))
  const out: { a: AgentRow; depth: number }[] = []
  const walk = (parent: string | undefined, depth: number) => {
    for (const r of rows) {
      const p = r.parentId !== undefined && ids.has(r.parentId) ? r.parentId : undefined
      if (p === parent && !out.some(o => o.a === r) && depth < 6) {
        out.push({ a: r, depth })
        walk(r.id, depth + 1)
      }
    }
  }
  walk(undefined, 0)
  return out
}

// A turn's end reason as the agent's final status.
export const endStatus = (reason: string): string =>
  reason === 'aborted' ? 'killed' : reason === 'error' || reason === 'refusal' ? 'failed' : 'completed'

// ---------------------------------------------------------------- state updates

const toContext = (c: SessionContextUsage): Context => ({
  tokens: c.tokens,
  window: c.window,
  percent: c.percent,
})

const add = <T extends Tokens>(a: T, t: TurnUsage): T => ({
  ...a,
  input: a.input + t.input_tokens,
  output: a.output + t.output_tokens,
  cacheRead: a.cacheRead + t.cache_read_input_tokens,
  cacheWrite: a.cacheWrite + t.cache_creation_input_tokens,
})

export const addMainTurn = (u: Usage, t: TurnUsage): Usage => ({
  ...u,
  model: t.model,
  main: { ...add(u.main, t), turns: u.main.turns + 1 },
  turns: [...u.turns, add({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0, model: t.model }, t)].slice(
    -KEEP_TURNS,
  ),
})

const blankAgent = (id: string): AgentRow => ({
  id,
  type: 'agent',
  description: '',
  model: '',
  status: 'running',
  runs: 0,
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
})

// A new row takes the next seq, so marks never shift. Trimming drops the oldest rows that
// have ended and are not being viewed; running ones always stay.
export const upsertAgent = (u: Usage, id: string, change: (a: AgentRow) => AgentRow, now?: number): Usage => {
  const found = u.agents.find(a => a.id === id)
  const seq = u.nextSeq ?? u.agents.length
  const next = change(found ?? { ...blankAgent(id), seq, startedAt: now })
  const agents = found ? u.agents.map(a => (a.id === id ? next : a)) : [...u.agents, next]
  let extra = agents.length - KEEP_AGENTS
  const kept = agents.filter(a => !(extra > 0 && !isLive(a) && !isIdle(a) && a.id !== u.viewing && extra-- > 0))
  return { ...u, agents: kept, nextSeq: found ? (u.nextSeq ?? u.agents.length) : seq + 1 }
}

export const tagOf = (a: AgentRow | undefined, u: Usage) => agentTag(a ? (a.seq ?? u.agents.indexOf(a)) : 0)

export const addAgentRun = (u: Usage, id: string, t: TurnUsage): Usage =>
  upsertAgent(u, id, a => ({ ...add(a, t), model: t.model, runs: a.runs + 1 }))

const statusText = (u: Usage): string | undefined => {
  const parts: string[] = []
  const pct = u.context?.percent
  if (pct !== undefined) parts.push(`${contextState(pct).icon} ${pct}%`)
  if (u.model) parts.push(`main ${modelName(u.model)}${u.effort ? ` ${u.effort}` : ''}`)
  const all = u.agents.reduce(
    (s, a) => ({ i: s.i + inputOf(a), o: s.o + a.output }),
    { i: inputOf(u.main), o: u.main.output },
  )
  if (all.i + all.o > 0) parts.push(`↑${fmt(all.i)} ↓${fmt(all.o)}`)
  const five = u.limits?.find(l => l.kind === 'five_hour')
  if (five) parts.push(`⏳${Math.round(five.percentUsed)}% ${resetsIn(five.resetsAt, Date.now())}`.trimEnd())
  const live = u.agents.filter(isLive).length
  if (live) parts.push(`🤖${live}`)
  return parts.length ? parts.join(' · ') : undefined
}

const publish = async ($: EngineInterface) => {
  $.ui.status(statusText(await read($, usage)))
}

// Fill in an agent's type, task and status from the engine's roster.
const syncAgents = async ($: EngineInterface) => {
  const roster = await $.agent.list()
  await update($, usage, u => ({
    ...u,
    agents: u.agents.map(a => {
      const info = roster.find(r => r.id === a.id)
      // Gone from the roster while still marked running: it ended without telling us.
      if (!info && isLive(a) && known.has(a.id)) return { ...a, status: 'killed', endedAt: a.endedAt ?? Date.now() }
      return info
        ? {
            ...a,
            type: info.type,
            parentId: info.parentId,
            description: info.description,
            status: info.status,
            endedAt: ['completed', 'failed', 'killed'].includes(info.status) ? (a.endedAt ?? Date.now()) : a.endedAt,
          }
        : a
    }),
  }))
}

const AGENT_PANE = 'agent-view'
// `viewing` set to this shows every subagent of the session to pick from.
const AGENT_LIST = '*'

// What a tool call looks at, in a few words: "Read stockbot/cli.py", "Bash grep -n add_parser".
export const activityOf = (tool: string, input: Record<string, unknown>): string => {
  const key = ['file_path', 'path', 'pattern', 'command', 'url', 'query', 'description', 'prompt'].find(
    k => typeof input[k] === 'string' && input[k] !== '',
  )
  const arg = key ? String(input[key]).split('\n')[0] ?? '' : ''
  const short = key === 'file_path' || key === 'path' ? arg.split('/').slice(-2).join('/') : arg
  return clip(`${tool} ${short}`.trim(), 60)
}

type Line = { kind: 'ask' | 'say' | 'tool' | 'result'; text: string; arg?: string; isError?: boolean }

// A subagent's messages as the main transcript draws them: "> prompt", "● reply",
// "● Read(path)" and its "⎿ result" under it, one entry per screen row.
export const transcriptLines = (messages: readonly SessionMessage[], width: number): Line[] => {
  const out: Line[] = []
  const wrap = (text: string, prefix: string, max: number) =>
    text
      .split('\n')
      .filter(l => l.trim())
      .slice(0, max)
      .map((l, i) => `${i === 0 ? prefix : ' '.repeat(prefix.length)}${clip(l, width - prefix.length)}`)
  for (const m of messages) {
    const text = m.text.trim()
    if (m.role === 'user') {
      if (text) for (const t of wrap(text, '> ', 4)) out.push({ kind: 'ask', text: t })
      continue
    }
    if (text) for (const t of wrap(text, '● ', 6)) out.push({ kind: 'say', text: t })
    for (const t of m.toolUses) {
      const act = activityOf(t.tool, t.input)
      out.push({ kind: 'tool', text: t.tool, arg: clip(act.slice(t.tool.length).trim(), width - t.tool.length - 6) })
      const res = t.text?.split('\n').find(l => l.trim())
      out.push({
        kind: 'result',
        text: res === undefined ? (t.result === undefined ? 'running…' : 'done') : clip(res.trim(), width - 6),
        isError: t.isError === true,
      })
    }
  }
  return out
}

const ctxPercent = (a: AgentRow, u: Usage): number | undefined =>
  a.ctxTokens ? Math.min(100, Math.round((a.ctxTokens / windowFor(a.model, u)) * 100)) : undefined

// Engine forks (compaction, memory) and workflow agents carry ids the roster never lists:
// only ids the roster knows get a row, so no row is left "running" forever.
// A miss is rechecked after a few seconds, in case the roster was still catching up.
const known = new Set<string>()
const ignored = new Map<string, number>()
const RECHECK_MS = 3000
const isTracked = async ($: EngineInterface, id: string): Promise<boolean> => {
  if (known.has(id)) return true
  const now = await $.clock.now()
  const missedAt = ignored.get(id)
  if (missedAt !== undefined && now - missedAt < RECHECK_MS) return false
  const roster = await $.agent.list().catch(() => [])
  for (const r of roster) known.add(r.id)
  if (known.has(id)) ignored.delete(id)
  else ignored.set(id, now)
  return known.has(id)
}

// Redraw once a second while a subagent runs, so its elapsed time counts up.
let isTicking = false
const tick = async ($: EngineInterface) => {
  if (isTicking) return
  isTicking = true
  try {
    while ((await read($, usage)).agents.some(isLive)) {
      await $.clock.sleep(1000)
      $.ui.invalidate('ui.render')
    }
  } catch {
    // No clock (a test, a host without timers): the time still updates on each event.
  } finally {
    isTicking = false
  }
}

// A press on a subagent's row opens its transcript in a pane; pressing the one shown closes it.
type View = { columns?: number; rows?: number } | undefined

// Closing never depends on the subagent still being there: its row, its tab, or the
// view itself can be gone (/clear, a trimmed row) while the pane is still up.
const closeAgentView = async ($: EngineInterface) => {
  await update($, usage, x => ({ ...x, viewing: undefined }))
  await $.ui.close({ id: AGENT_PANE }).catch(() => undefined)
}

// Opened focused and near full size, so it reads as the main view switching to that agent.
const toggleAgentView = async ($: EngineInterface, id: string, view: View, isTab = false) => {
  const u = await read($, usage)
  if (u.viewing === id) {
    // A tab already shown stays; the row's name toggles the pane shut.
    if (isTab) return
    await closeAgentView($)
    return
  }
  const a = u.agents.find(x => x.id === id)
  const tag = tagOf(a, u)
  await update($, usage, x => ({ ...x, viewing: id }))
  const cols = view?.columns ?? 100
  const placed = await $.ui.open({
    id: AGENT_PANE,
    title: id === AGENT_LIST ? 'Subagents' : `${tag.mark} ${a?.description || a?.type || 'subagent'}`,
    focus: true,
    closeOnEscape: true,
    rows: Math.max(6, (view?.rows ?? 30) - 8),
    columns: Math.max(20, Math.min(cols - 2, cols - 20)),
  })
  if (!placed.isPlaced) {
    await update($, usage, x => ({ ...x, viewing: undefined }))
    await $.ui.close({ id: AGENT_PANE }).catch(() => undefined)
    $.ui.toast('No room to open the pane. Widen the terminal and try again.', { timeoutMs: 5000 })
  }
}

// ---------------------------------------------------------------- hooks

type Opts = { isBandOn: boolean; hasResetTimes: boolean; agentRows: number; hasActivity: boolean; theme?: string }
export const optsFrom = (o: Readonly<Record<string, unknown>>): Opts => ({
  isBandOn: o.band !== false,
  hasResetTimes: o.resetTimes === true,
  agentRows: o.agentRows === 'off' ? 0 : Number(o.agentRows ?? 5) || 5,
  hasActivity: o.agentActivity !== false,
  theme: typeof o.theme === 'string' && o.theme in PRESETS ? o.theme : undefined,
})

// Settings come from /config (userConfig); a change there reloads the module.
export const register: Register = (on, options) => {
  const opts = optsFrom(options)
  const themeOf = (u: Usage): Palette => (opts.theme ? palette({ preset: opts.theme, overrides: {} }) : themeFrom(u))

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'token-usage',
      description: 'Expand/collapse usage details above the prompt (context, limits, models, subagents). Settings: /config',
      argumentHint: '[open|close|band on|off|theme [name]|color <slot> <#hex>]',
    })
    const theme = await loadTheme($)
    await update($, usage, u => ({ ...u, theme }))
    await freshen($)
    await publish($)
    return next(e)
  })

  on('command.run', { command: 'token-usage' }, async ($, e) => {
    const arg = e.args.trim()
    const words = arg.split(/\s+/)
    if (words[0] === 'theme' || words[0] === 'color') {
      if (opts.theme) return { text: `The token-usage color theme is set to "${opts.theme}" in /config, so this command cannot change it. Set it to 'theme file' in /config and try again.` }
      const r = await themeCommand($, words)
      if (r.theme) {
        const theme = r.theme
        await update($, usage, u => ({ ...u, theme }))
      }
      return { text: r.text }
    }
    if (arg === 'band off' || arg === 'band on') {
      const r = await $.config.set({ key: 'token-usage.band', value: arg === 'band on' }).catch(() => ({ deny: 'error' }))
      if ('deny' in r && r.deny !== undefined) await update($, usage, u => ({ ...u, isBandHidden: arg === 'band off' }))
      return { text: arg === 'band off' ? 'Usage line hidden.' : 'Usage line shown.' }
    }
    if (arg === 'close' || arg === 'open' || arg === '') {
      if (arg === 'close') await closeAgentView($)
      await freshen($)
      const isExpanded = arg === 'open' || (arg === '' && !(await read($, usage)).isExpanded)
      await update($, usage, u => ({ ...u, isExpanded, isBandHidden: false }))
      return { text: isExpanded ? 'Usage details expanded. Run /token-usage again to collapse.' : 'Usage details collapsed.' }
    }
    return { text: 'Usage: /token-usage (expand/collapse), /token-usage band on|off, /token-usage theme. Other settings: /config' }
  })

  on('session.measure', async ($, e, next) => {
    await update($, usage, u => {
      return { ...u, context: toContext(e.context), limits: toLimits(e.rateLimits) }
    })
    if ((await read($, usage)).agents.some(isLive)) await syncAgents($).catch(() => undefined)
    await publish($)
    return next(e)
  })

  // The pane closed (Esc, its close mark, or a press): nothing is viewed any more.
  on('ui.close', async ($, e, next) => {
    const r = await next(e)
    if (e.id === AGENT_PANE) await update($, usage, u => ({ ...u, viewing: undefined }))
    return r
 }).catch(($, e, next) => next(e))

  // /clear starts over: rows of the old conversation would never finish.
  on('session.end', async ($, e, next) => {
    if (e.reason === 'clear') {
      known.clear()
      ignored.clear()
      // The pane would show a subagent that no longer exists, with no row left to close it.
      await closeAgentView($)
      await update($, usage, u => ({ ...EMPTY, theme: u.theme, limits: u.limits, model: u.model, effort: u.effort }))
    }
    return next(e)
  })

  // Every model request names its model: the live model of main and of each subagent.
  on('turn.step', async function* ($, e, next) {
    const agentId = e.agentId
    if (agentId !== undefined && !(await isTracked($, agentId).catch(() => false))) return yield* next(e)
    const now = await $.clock.now()
    await update($, usage, u =>
      agentId === undefined
        ? { ...u, model: e.model, effort: e.effort === undefined ? u.effort : String(e.effort) }
        : upsertAgent(u, agentId, a => ({
            ...a,
            model: e.model,
            effort: e.effort === undefined ? a.effort : String(e.effort),
            status: isLive(a) || a.runs === 0 ? 'running' : a.status,
          }), now),
    )
    if (agentId !== undefined) void tick($)
    if (agentId !== undefined && e.index === 0) {
      await syncAgents($)
      await publish($)
    }
    const r = yield* next(e)
    const used = r.usage
    if (agentId !== undefined && used) {
      const ctxSum = used.input_tokens + used.cache_read_input_tokens + used.cache_creation_input_tokens
      await update($, usage, u => upsertAgent(u, agentId, a => ({ ...a, ctxTokens: ctxSum })))
    }
    return r
  })

  on('tool.call', async ($, e, next) => {
    const agentId = e.agentId
    if (agentId !== undefined && (await isTracked($, agentId))) {
      const activity = activityOf(e.tool, e as unknown as Record<string, unknown>)
      const now = await $.clock.now()
      await update($, usage, u => upsertAgent(u, agentId, a => ({ ...a, activity }), now))
      void tick($)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    const t = e.usage
    const agentId = e.agentId
    if (agentId !== undefined && !(await isTracked($, agentId).catch(() => false))) return done
    if (t) {
      await update($, usage, u =>
        agentId === undefined ? addMainTurn(u, t) : addAgentRun(u, agentId, t),
      )
    }
    if (agentId !== undefined) {
      await syncAgents($).catch(() => undefined)
      // A subagent's turn ending is its run ending, even if the roster has not caught up yet.
      // A teammate goes idle instead, and the roster says so.
      const now = await $.clock.now()
      const status = endStatus(e.reason)
      await update($, usage, u =>
        upsertAgent(u, agentId, a => (isLive(a) ? { ...a, status, endedAt: a.endedAt ?? now } : a)),
      )
      const u = await read($, usage)
      const a = u.agents.find(x => x.id === agentId)
      if (a && u.viewing === agentId) {
        const tag = tagOf(a, u)
        const how = a.status === 'completed' ? 'done' : a.status === 'idle' ? 'waiting for a message' : `stopped (${STATUS_LABEL[a.status] ?? a.status})`
        $.ui.toast(`${tag.mark} ${a.description || a.type} ${how}: the result stays in the open pane`, { timeoutMs: 6000 })
      }
    } else {
      const theme = await loadTheme($)
      await update($, usage, u => ({ ...u, theme }))
      // A subagent stopped without its own turn.complete is caught here.
      if (u0Live(await read($, usage))) await syncAgents($).catch(() => undefined)
    }
    await publish($)
    return done
  })

  // ------------------------------------------------------------ band

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const u = await read($, usage)
    const below = await next(e)
    if (e.props.hasSurvey || u.isBandHidden || (!opts.isBandOn && !u.isExpanded)) return below

    const { Box, Button, Text } = $.ui.resolve(e)
    const P = themeOf(u)
    const cols = e.viewport?.columns ?? 80
    const now = await $.clock.now()
    const pct = u.context?.percent
    const st = pct !== undefined ? contextState(pct) : null
    const limits = u.limits ?? []
    const live = u.agents.filter(a => isLive(a) || isIdle(a))
    const isNarrow = cols < 80
    const sep = <Text dimColor> │ </Text>
    const short = (kind: string) => (kind === 'five_hour' ? '5h' : kind === 'seven_day' ? '7d' : limitLabel(kind))
    const effortText = (x?: string) => (x ? <Text dimColor> {x}</Text> : null)
    // A subagent's request often carries no effort; say so rather than leave a gap.
    const agentEffort = (a: AgentRow) =>
      a.effort ? <Text color={P.accent}> effort {a.effort}</Text> : a.model ? <Text dimColor> no effort</Text> : null

    const line = (
      <Text>
        <Text>🧠 </Text>
        {st && pct !== undefined ? (
          <Text>
            <Text bold color={P[st.tone]}>
              {pct}%
            </Text>
            <Text color={P[st.tone]}> {fineBar(pct, 12)}</Text>
          </Text>
        ) : (
          <Text dimColor>no reply yet</Text>
        )}
        {limits.length > 0 && (
          <Text>
            {sep}⏳{' '}
            {limits.map((l, i) => (
              <Text>
                {i > 0 && <Text dimColor> · </Text>}
                <Text dimColor>{short(l.kind)} </Text>
                <Text bold color={P[contextState(l.percentUsed).tone]}>
                  {Math.round(l.percentUsed)}%
                </Text>
                {opts.hasResetTimes && <Text dimColor> {resetsIn(l.resetsAt, now)}</Text>}
              </Text>
            ))}
          </Text>
        )}
        {u.model && (
          <Text>
            {sep}
            {live.length > 0 && <Text dimColor>main </Text>}
            <Text bold color={P.accent}>
              {modelName(u.model).replace(/ 1M$/, '')}
            </Text>
            {effortText(u.effort)}
          </Text>
        )}
      </Text>
    )

    // One row per running subagent, so each model sits next to its own job.
    const MAX_AGENT_ROWS = opts.agentRows
    const viewing = u.viewing
    const nameWidth = isNarrow ? 14 : 24
    const agentRows = [
      // The agent being viewed keeps its row after it finishes, until its pane is closed.
      ...nested([...live.slice(0, MAX_AGENT_ROWS), ...u.agents.filter(x => x.id === viewing && !live.slice(0, MAX_AGENT_ROWS).includes(x))]).map(({ a, depth }) => {
        const tag = tagOf(a, u)
        const cp = ctxPercent(a, u)
        const isViewing = a.id === viewing
        const took = agentElapsed(a, now)
        return (
          <Box key={`agent:${a.id}`}>
            <Text color={P.accent}>{isViewing ? '👁 ' : '  '}</Text>
            {depth > 0 && <Text dimColor>{`${'  '.repeat(depth - 1)}└ `}</Text>}
            <Text bold color={P[tag.tone]}>{tag.mark} </Text>
            <Button
              key={`agent:${a.id}`}
              plain
              label={fit(clip(a.description || a.type, nameWidth), nameWidth)}
              onPress={() => toggleAgentView($, a.id, e.viewport)}
            />
            <Text> </Text>
            <Text bold>{a.model ? modelName(a.model).replace(/ 1M$/, '') : '?'}</Text>
            {agentEffort(a)}
            {!isLive(a) && (
              <Text color={a.status === 'completed' ? P.ok : isIdle(a) ? P.cache : P.danger}>
                {' '}
                {a.status === 'completed' ? '✓' : isIdle(a) ? '◌' : '✗'} {STATUS_LABEL[a.status] ?? a.status}
              </Text>
            )}
            {took && <Text dimColor> │ ⏱ {took}</Text>}
            <Text dimColor> │ ctx </Text>
            {cp !== undefined ? (
              <Text color={P[contextState(cp).tone]}>
                {isNarrow ? '' : `${fineBar(cp, 6)} `}
                {cp}%
              </Text>
            ) : (
              <Text dimColor>-</Text>
            )}
            {opts.hasActivity && !isNarrow && a.activity && <Text dimColor> │ {clip(a.activity, Math.max(10, cols - nameWidth - 62))}</Text>}
          </Box>
        )
      }),
      ...(MAX_AGENT_ROWS > 0 && live.length > MAX_AGENT_ROWS
        ? [
            <Box key="agent:more">
              <Text>{viewing === AGENT_LIST ? '👁 ' : '   '}</Text>
              <Button
                key="agent:more"
                plain
                label={`🤖 +${live.length - MAX_AGENT_ROWS} more`}
                onPress={() => toggleAgentView($, AGENT_LIST, e.viewport)}
              />
            </Box>,
          ]
        : []),
    ]

    if (!u.isExpanded) {
      return (
        <Box flexDirection="column">
          {line}
          {agentRows}
          {below}
        </Box>
      )
    }

    const W = 12
    const all = [u.main, ...u.agents]
    const sum = (k: keyof Tokens) => all.reduce((s, t) => s + t[k], 0)
    const totals: Tokens = { input: sum('input'), output: sum('output'), cacheRead: sum('cacheRead'), cacheWrite: sum('cacheWrite') }
    const cachePct = inputOf(totals) ? Math.round((totals.cacheRead / inputOf(totals)) * 100) : 0
    const row = (label: string, value: number, tone: string, detail: string) => (
      <Text>
        <Text>{'  '}{fit(label, 11)}</Text>
        <Text color={tone}>{fineBar(value, W)}</Text>
        <Text bold> {String(Math.round(value)).padStart(3)}%</Text>
        <Text dimColor>  {detail}</Text>
      </Text>
    )
    const agentsShown = [...live, ...u.agents.filter(a => !isLive(a)).reverse()].slice(0, 6)
    const modelCell = (model: string, effort?: string) => fit(`${model ? modelName(model) : '?'} ${effort ?? '(no effort)'}`, 30)

    return (
      <Box flexDirection="column">
        {line}
        {st && pct !== undefined && u.context && row('context', pct, P[st.tone], `${fmt(u.context.tokens ?? 0)}/${fmt(u.context.window)} ${st.label}`)}
        {limits.map(l => row(`${limitLabel(l.kind)} limit`, l.percentUsed, P[contextState(l.percentUsed).tone], resetsIn(l.resetsAt, now)))}
        {row('cache hit', cachePct, P.ok, `↑${fmt(inputOf(totals))} ↓${fmt(totals.output)}`)}
        <Text dimColor>{'  ─ models '.padEnd(Math.min(60, cols - 4), '─')}</Text>
        <Text>
          <Text>{'  '}</Text>
          <Text color={P.accent}>● </Text>
          <Text bold>{fit('main', 20)}</Text>
          <Text color={P.accent}>{modelCell(u.model ?? '', u.effort)}</Text>
          {st && pct !== undefined ? (
            <Text>
              <Text color={P[st.tone]}>{fineBar(pct, 8)}</Text>
              <Text bold> {String(pct).padStart(3)}%</Text>
            </Text>
          ) : (
            <Text dimColor>{'·'.repeat(8)}    -</Text>
          )}
          <Text dimColor>  ↓{fmt(u.main.output)}</Text>
        </Text>
        {agentsShown.map(a => {
          const as = AGENT_ICON[a.status] ?? { icon: '·', tone: 'cache' as const }
          const win = windowFor(a.model, u)
          const cp = a.ctxTokens ? Math.min(100, Math.round((a.ctxTokens / win) * 100)) : undefined
          return (
            <Text>
              <Text>{'  '}</Text>
              <Text color={P[as.tone]}>{as.icon} </Text>
              <Text bold color={P[tagOf(a, u).tone]}>{fit(`${tagOf(a, u).mark} ${clip(a.description || a.type, 16)}`, 20)}</Text>
              <Text color={P.warn}>{modelCell(a.model, a.effort)}</Text>
              {cp !== undefined ? (
                <Text>
                  <Text color={P[contextState(cp).tone]}>{fineBar(cp, 8)}</Text>
                  <Text bold> {String(cp).padStart(3)}%</Text>
                </Text>
              ) : (
                <Text dimColor>{'·'.repeat(8)}    -</Text>
              )}
              <Text dimColor>
                {'  '}↓{fmt(a.output)}
              </Text>
            </Text>
          )
        })}
        <Text dimColor>
          {'  '}theme {(u.theme as ThemeFile | undefined)?.preset ?? 'default'} · /token-usage theme · collapse: /token-usage
        </Text>
        {below}
      </Box>
    )
  })


  // ------------------------------------------------------------ agent pane

  on('ui.render', { component: 'Pane', requestId: AGENT_PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const u = await read($, usage)
    const P = themeOf(u)
    const { Button } = $.ui.resolve(e)
    const width = Math.max(20, (e.props.bodyColumns ?? e.viewport?.columns ?? 60) - 2)
    const view = e.viewport
    // Running first, then the latest finished: every subagent stays one press away.
    const nowMs = await $.clock.now()
    const ordered = [...u.agents.filter(isLive), ...u.agents.filter(x => !isLive(x)).reverse()]
    const tabs = (
      <Box key="tabs" flexWrap="wrap">
        <Button key="tab:*" plain label={u.viewing === AGENT_LIST ? '[list]' : ' list '} onPress={() => toggleAgentView($, AGENT_LIST, view, true)} />
        {ordered.slice(0, 12).map(x => {
          const t = tagOf(x, u)
          const isOn = x.id === u.viewing
          return (
            <Button
              key={`tab:${x.id}`}
              plain
              label={`${isOn ? '[' : ' '}${t.mark}${isLive(x) ? '' : '✓'} ${clip(x.description || x.type, 10)}${isOn ? ']' : ' '}`}
              onPress={() => toggleAgentView($, x.id, view, true)}
            />
          )
        })}
        <Button key="tab:close" plain label=" ✕ close " onPress={() => closeAgentView($)} />
      </Box>
    )
    if (u.viewing === AGENT_LIST) {
      return (
        <Box flexDirection="column">
          {tabs}
          <Text dimColor>{'─'.repeat(Math.min(width, 80))}</Text>
          {ordered.length === 0 && <Text dimColor>No subagents yet.</Text>}
          {nested(ordered).map(({ a: x, depth }) => {
            const t = tagOf(x, u)
            const xp = ctxPercent(x, u)
            return (
              <Box key={`row:${x.id}`}>
                {depth > 0 && <Text dimColor>{`${'  '.repeat(depth - 1)}└ `}</Text>}
                <Text bold color={P[t.tone]}>{t.mark} </Text>
                <Button key={`pick:${x.id}`} plain label={fit(clip(x.description || x.type, 24), 24)} onPress={() => toggleAgentView($, x.id, view, true)} />
                <Text bold> {x.model ? modelName(x.model).replace(/ 1M$/, '') : '?'}</Text>
                <Text dimColor> effort {x.effort ?? 'none'}</Text>
                <Text color={isLive(x) ? P.warn : x.status === 'completed' ? P.ok : isIdle(x) ? P.cache : P.danger}> {STATUS_LABEL[x.status] ?? x.status}</Text>
                {agentElapsed(x, nowMs) && <Text dimColor> · ⏱ {agentElapsed(x, nowMs)}</Text>}
                <Text dimColor> · ctx {xp !== undefined ? `${xp}%` : '-'}</Text>
                {x.activity && <Text dimColor> · {clip(x.activity, Math.max(10, width - 70))}</Text>}
              </Box>
            )
          })}
        </Box>
      )
    }
    const a = u.agents.find(x => x.id === u.viewing)
    if (!a) {
      const why = u.viewing ? "This subagent's work is no longer kept." : 'Click a subagent name in the row above to see its work here.'
      return <Box flexDirection="column">{tabs}<Text dimColor>{why} ✕ close or Esc: back to main.</Text></Box>
    }
    const tag = tagOf(a, u)
    const cp = ctxPercent(a, u)
    const found = await $.session.messages({ agentId: a.id }).catch(() => ({ deny: 'error' }) as const)
    const lines = transcriptLines('deny' in found ? [] : found, width)
    const room = Math.max(3, (e.viewport?.rows ?? 24) - 6)
    const STATUS = STATUS_LABEL
    const took = agentElapsed(a, await $.clock.now())
    const isLiveNow = isLive(a)
    return (
      <Box flexDirection="column">
        {tabs}
        <Text>
          <Text backgroundColor={P[tag.tone]} color={P.chipText} bold>
            {` ${tag.mark} ${a.description || a.type} `}
          </Text>
          <Text bold> {a.model ? modelName(a.model) : '?'}</Text>
          <Text dimColor> · effort {a.effort ?? 'none'}</Text>
          <Text color={isLiveNow ? P.warn : P.ok}> · {STATUS[a.status] ?? a.status}</Text>
          {took && <Text dimColor> · ⏱ {took}</Text>}
          <Text dimColor> · ctx {cp !== undefined ? `${cp}%` : '-'} · Esc: back to main</Text>
        </Text>
        {'deny' in found && <Text dimColor>Cannot read this subagent's transcript.</Text>}
        {lines.slice(-room).map(l =>
          l.kind === 'ask' ? (
            <Text dimColor>{l.text}</Text>
          ) : l.kind === 'tool' ? (
            <Text>
              <Text color={P.ok}>● </Text>
              <Text bold>{l.text}</Text>
              {l.arg && <Text>({l.arg})</Text>}
            </Text>
          ) : l.kind === 'result' ? (
            <Text color={l.isError ? P.danger : undefined} dimColor={!l.isError}>
              {'  ⎿  '}
              {l.text}
            </Text>
          ) : (
            <Text>{l.text}</Text>
          ),
        )}
        {isLiveNow ? (
          <Text color={P.warn}>✻ working…</Text>
        ) : (
          <Text color={a.status === 'completed' ? P.ok : P.danger}>
            {a.status === 'completed' ? `✓ Done${took ? ` (took ${took})` : ''}.` : isIdle(a) ? '◌ Waiting for a message.' : `✗ Stopped (${STATUS[a.status] ?? a.status}).`} Other subagents: tabs above. Esc: back to main.
          </Text>
        )}
      </Box>
    )
  })
}
