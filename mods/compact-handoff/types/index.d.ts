export type Task = { subject: string; status: string }

export type Handoff = {
  prompts: string[]
  tasks: Task[]
  files: string[]
  failures: string[]
  lastStep: string
}

export type AgentLine = { type: string; description: string; status: string }

export type Summary = {
  handoff: Handoff
  agents: AgentLine[]
  updatedAt: number
  isBandHidden: boolean
  cwd: string
  isExpanded: boolean
  theme: { preset: string; overrides: Record<string, string> }
}

declare module 'claude-code' {
  interface PluginState {
    'compact-handoff': {
      summary: Summary
    }
  }
}
