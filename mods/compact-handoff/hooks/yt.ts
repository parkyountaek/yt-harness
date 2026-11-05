// yt-harness tasks, as `yt panel --json` reports them. Shared by the three mods: keep
// every copy identical (tests/mods/run.sh checks). The mods only show and alert;
// every action stays a yt command, so Claude and Codex sessions run tasks the same way.
import type { EngineInterface } from 'claude-code'

export type YtNeed = 'question' | 'deadline' | 'collect' | 'ended'
export type YtTask = {
  taskId: string
  harness?: string
  runtime?: string
  runner?: string
  state?: string
  deadline?: string
  since?: string
  need: YtNeed | null
  question?: string
  command?: string | null
}
export type YtSnapshot = { counts: Record<string, number>; tasks: YtTask[] }

export const YT_POLL_MS = 15_000

// The mods live at <checkout>/mods/<mod>; yt is at <checkout>/yt-core/bin/yt.
export const ytBin = (root: string): string => `${root.replace(/\/+$/, '').replace(/\/mods\/[^/]+$/, '')}/yt-core/bin/yt`

export const parseSnapshot = (text: string): YtSnapshot | undefined => {
  try {
    const s = JSON.parse(text) as { schema?: number; counts?: unknown; tasks?: unknown }
    if (s.schema !== 1 || !Array.isArray(s.tasks) || typeof s.counts !== 'object' || s.counts === null) return undefined
    return { counts: s.counts as Record<string, number>, tasks: s.tasks as YtTask[] }
  } catch {
    return undefined
  }
}

// undefined when yt is missing or fails: the mods then show nothing about tasks.
export async function readYt($: EngineInterface): Promise<YtSnapshot | undefined> {
  const r = await $.process.run([ytBin($.plugin.root), 'panel', '--json'], { timeoutMs: 10_000 }).catch(() => undefined)
  return r && r.exitCode === 0 ? parseSnapshot(r.stdout) : undefined
}

export const NEED_TEXT: Record<YtNeed, string> = {
  question: 'asks',
  deadline: 'is past its deadline',
  collect: 'finished, not collected',
  ended: 'ended without reporting',
}

// One short line per task that needs the human, with the command that deals with it.
export const needLine = (t: YtTask): string => {
  const what = t.need === 'question' ? `asks: ${t.question ?? ''}` : t.need === 'collect' ? `${t.state ?? 'done'}, not collected` : t.need ? NEED_TEXT[t.need] : (t.state ?? 'running')
  return `${t.taskId} ${what}${t.command ? ` → ${t.command}` : ''}`
}
