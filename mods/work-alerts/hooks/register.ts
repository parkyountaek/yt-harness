import type { EngineInterface, Register } from 'claude-code'

// Settings come from /config (this plugin's userConfig); a change there reloads the module.
type Prefs = { isOn: boolean; hasSound: boolean; hasDesktop: boolean; longTurnSec: number; subagent: string }
const LONG_TURN: Record<string, number> = { '30s': 30, '60s': 60, '2m': 120, '5m': 300 }

export const prefsFrom = (o: Readonly<Record<string, unknown>>): Prefs => ({
  isOn: o.enabled !== false,
  hasSound: o.sound !== false,
  hasDesktop: o.desktop !== false,
  longTurnSec: LONG_TURN[String(o.longTurn)] ?? 60,
  subagent: typeof o.subagent === 'string' ? o.subagent : 'popup only',
})

const SOUND = {
  done: '/System/Library/Sounds/Glass.aiff',
  fail: '/System/Library/Sounds/Basso.aiff',
  warn: '/System/Library/Sounds/Funk.aiff',
} as const

// Commands whose failure is worth an alert: tests, lint, type checks, builds.
const CHECK = /\b(pytest|ruff|mypy|tsc|jest|vitest|npm (run )?test|cargo test|go test|make)\b/

export const duration = (ms: number): string => {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return s % 60 ? `${m}m ${s % 60}s` : `${m}m`
}

// The line a test runner ends on ("== 2 failed, 120 passed in 3.1s ==", "Found 3 errors").
export const failSummary = (out: string): string | undefined => {
  const lines = out.split('\n').map(l => l.trim()).filter(Boolean)
  const hit = [...lines]
    .reverse()
    .find(l => /\b(failed|error|errors|FAILED)\b/.test(l) && l.length < 200)
  return hit?.replace(/^=+\s*|\s*=+$/g, '')
}

// Which threshold a value has newly crossed upward, if any.
export const crossed = (before: number, now: number, levels: readonly number[]): number | undefined =>
  [...levels].reverse().find(l => before < l && now >= l)

const quote = (s: string) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')

let prefs: Prefs = prefsFrom({})
// Several alerts at once (parallel subagents finishing) play one sound.
let lastSoundAt = 0

async function alert($: EngineInterface, text: string, kind: keyof typeof SOUND, isDesktop = false, hasSound = true) {
  if (!prefs.isOn) return
  $.ui.toast(text, { timeoutMs: kind === 'fail' ? 8000 : 5000 })
  const now = await $.clock.now()
  if (prefs.hasSound && hasSound && now - lastSoundAt > 2000) {
    lastSoundAt = now
    void $.process.run(['afplay', SOUND[kind]]).catch(() => undefined)
  }
  if (prefs.hasDesktop && isDesktop) {
    const script = `display notification "${quote(text)}" with title "Claude Code"`
    void $.process.run(['osascript', '-e', script]).catch(() => undefined)
  }
}

const flag = (x: boolean) => (x ? 'on' : 'off')
const describe = (p: Prefs) =>
  `Work alerts ${flag(p.isOn)} · sound ${flag(p.hasSound)} · macOS popup ${flag(p.hasDesktop)} · only replies over ${p.longTurnSec}s · subagents: ${p.subagent}`

// Commands write through /config, so the menu and the commands never disagree.
async function setOption($: EngineInterface, field: string, value: boolean | string): Promise<boolean> {
  const r = await $.config.set({ key: `work-alerts.${field}`, value }).catch(() => ({ deny: 'error' }))
  return !('deny' in r && r.deny !== undefined)
}

export const register: Register = (on, options) => {
  prefs = prefsFrom(options)
  // undefined until the first reading, so a session that starts above a line does not alert.
  let lastContext: number | undefined
  const lastLimit = new Map<string, number>()

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'alerts',
      description: 'Show work alert settings (change: work-alerts in /config, try: /alerts test)',
      argumentHint: '[test]',
    })
    await $.command.register({ name: 'task-alert', description: 'Turn the alert sound on/off (on|off, empty toggles)', argumentHint: '[on|off]' })
    return next(e)
  })

  // /task-alert flips the alert sound; toasts and desktop notices are untouched.
  on('command.run', { command: 'task-alert' }, async ($, e) => {
    const a = e.args.trim()
    const hasSound = a === 'on' ? true : a === 'off' ? false : !prefs.hasSound
    if (!(await setOption($, 'sound', hasSound))) prefs = { ...prefs, hasSound }
    return { text: hasSound ? '🔔 Alert sound on' : '🔕 Alert sound off (popups still show)' }
  })

  on('command.run', { command: 'alerts' }, async ($, e) => {
    if (e.args.trim() === 'test') {
      await alert($, '🔔 This is a test alert', 'done', true)
      return { text: prefs.isOn ? 'Test alert sent.' : 'Work alerts are off, so no test alert shows. Turn them on in /config.' }
    }
    return { text: `${describe(prefs)}\nTo change, pick work-alerts in /config.` }
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    const took = duration(e.durationMs)
    if (e.agentId !== undefined) {
      const info = (await $.agent.list()).find(a => a.id === e.agentId)
      const name = info ? `${info.type}${info.description ? ` · ${info.description}` : ''}` : 'subagent'
      if (prefs.subagent === 'off') return done
      const hasSound = prefs.subagent === 'popup and sound'
      if (e.reason === 'error') await alert($, `🤖✗ ${name} failed (${took})`, 'fail', false, hasSound)
      else if (!e.isAborted) await alert($, `🤖✓ ${name} done (${took})`, 'done', false, hasSound)
      return done
    }
    if (e.reason === 'error') await alert($, `✗ Stopped on an error (${took})`, 'fail', true)
    else if (e.reason === 'refusal') await alert($, `⚠ The model refused to answer`, 'warn', true)
    else if (!e.isAborted && e.durationMs >= prefs.longTurnSec * 1000) {
      await alert($, `✓ Done (${took}) — please check`, 'done', true)
    }
    return done
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && ran.isError === true && CHECK.test(e.command)) {
      const tool = CHECK.exec(e.command)?.[1] ?? 'check'
      const out = ran.result as { stdout?: string; stderr?: string } | undefined
      const why = failSummary(`${out?.stdout ?? ''}\n${out?.stderr ?? ''}`)
      await alert($, `🧪✗ ${tool} failed${why ? `: ${why}` : ''}`, 'fail')
    }
    return ran
  }).catch(($, e, next) => next(e))

  on('session.measure', async ($, e, next) => {
    const pct = e.context.percent
    if (pct !== undefined) {
      const hit = lastContext === undefined ? undefined : crossed(lastContext, pct, [60, 85])
      if (hit === 85) await alert($, `● Context ${pct}% — auto-compact soon`, 'warn')
      else if (hit === 60) await alert($, `◕ Context ${pct}% used`, 'warn')
      lastContext = pct
    }
    for (const limit of e.rateLimits) {
      const before = lastLimit.get(limit.kind)
      const hit = before === undefined ? undefined : crossed(before, limit.percentUsed, [80, 95])
      if (hit !== undefined) {
        const label = limit.kind === 'five_hour' ? '5h' : limit.kind === 'seven_day' ? '7d' : limit.kind
        await alert($, `⏳ ${label} usage limit ${limit.percentUsed}%`, 'warn', hit === 95)
      }
      lastLimit.set(limit.kind, limit.percentUsed)
    }
    return next(e)
  })
}
