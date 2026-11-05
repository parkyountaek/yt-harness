export type Tokens = {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
}

export type TurnRow = Tokens & { model: string }

export type AgentRow = Tokens & {
  id: string
  // Order of first appearance in the session: its ①② mark and color, never reused.
  seq?: number
  // When it was first seen and when its run ended (ms), for the elapsed time.
  startedAt?: number
  endedAt?: number
  type: string
  description: string
  model: string
  status: string
  runs: number
  effort?: string
  // Input of its latest request: how full its own context window is.
  ctxTokens?: number
  // Its latest tool call, as "Read docs/spec.md": what it is looking at now.
  activity?: string
  // The subagent that spawned this one; absent when the main loop did.
  parentId?: string
}

export type Limit = { kind: string; percentUsed: number; resetsAt?: string }

export type Context = { tokens?: number; window: number; percent?: number }

export type Usage = {
  // Main loop only; subagents are kept per agent in `agents`.
  main: Tokens & { turns: number }
  model: string | null
  effort?: string
  turns: TurnRow[]
  agents: AgentRow[]
  context: Context | null
  isBandHidden: boolean
  // Subscription rate-limit windows (five_hour, seven_day); absent before the first reading.
  limits?: Limit[]
  // Color theme, as the shared mods theme file holds it.
  theme?: { preset: string; overrides: Record<string, string> }
  // The band above the prompt drawn in detail (toggled by /token-usage).
  isExpanded?: boolean
  // The subagent whose transcript the agent pane shows, while that pane is open.
  viewing?: string
  // The next subagent's seq.
  nextSeq?: number
}

declare module 'claude-code' {
  interface PluginState {
    'token-usage': {
      usageV3: Usage
    }
  }
}
