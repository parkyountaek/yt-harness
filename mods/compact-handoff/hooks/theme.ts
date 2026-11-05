// One color theme shared by the token-usage and compact-handoff mods.
// Kept in ~/yt-local/mods-theme.json so either mod's command changes both.

export type Slot = 'ok' | 'warn' | 'danger' | 'input' | 'output' | 'cache' | 'accent' | 'chipText'
export type Palette = Record<Slot, string>
export type ThemeFile = { preset: string; overrides: Partial<Palette> }

export const SLOTS: readonly Slot[] = ['ok', 'warn', 'danger', 'input', 'output', 'cache', 'accent', 'chipText']

export const PRESETS: Record<string, Palette> = {
  // The terminal theme's own colors: follows /theme light or dark.
  default: {
    ok: 'success',
    warn: 'warning',
    danger: 'error',
    input: 'suggestion',
    output: 'claude',
    cache: 'inactive',
    accent: 'permission',
    chipText: 'inverseText',
  },
  // Okabe-Ito: distinguishable with common color-vision deficiencies.
  colorblind: {
    ok: '#009E73',
    warn: '#E69F00',
    danger: '#D55E00',
    input: '#56B4E9',
    output: '#CC79A7',
    cache: '#999999',
    accent: '#0072B2',
    chipText: '#000000',
  },
  ocean: {
    ok: '#2DD4BF',
    warn: '#FBBF24',
    danger: '#F87171',
    input: '#60A5FA',
    output: '#C084FC',
    cache: '#64748B',
    accent: '#38BDF8',
    chipText: '#0B1220',
  },
  vivid: {
    ok: '#22C55E',
    warn: '#F59E0B',
    danger: '#EF4444',
    input: '#3B82F6',
    output: '#F97316',
    cache: '#6B7280',
    accent: '#A855F7',
    chipText: '#000000',
  },
}

export const palette = (t: ThemeFile): Palette => {
  const base = PRESETS[t.preset] ?? PRESETS.default
  return { ...(base as Palette), ...t.overrides }
}

const isColor = (v: string) => /^#[0-9a-fA-F]{6}$/.test(v) || /^[a-zA-Z]+$/.test(v)

export const DEFAULT_THEME: ThemeFile = { preset: 'default', overrides: {} }

// Defaults to ~/yt-local/mods-theme.json. CLAUDE_MODS_THEME_FILE overrides it (yt-setup sets it),
// which also lets another account (root) share this user's theme file.
export const themePath = (home: string | undefined, file?: string) => file || `${home ?? '~'}/yt-local/mods-theme.json`

export const parseTheme = (text: string): ThemeFile => {
  try {
    const raw = JSON.parse(text) as Partial<ThemeFile>
    return { preset: raw.preset ?? 'default', overrides: raw.overrides ?? {} }
  } catch {
    return DEFAULT_THEME
  }
}

const show = (t: ThemeFile) =>
  `theme: ${t.preset} (${Object.keys(PRESETS).join(' | ')})\n` +
  SLOTS.map(s => `  ${s.padEnd(8)} ${palette(t)[s]}${t.overrides[s] ? '  (override)' : ''}`).join('\n')

// `theme`, `theme <preset>`, `color <slot> <#hex|theme-key>`, `color reset`.
// Returns the text to show and, when it changed, the theme to save.
export const applyThemeArgs = (now: ThemeFile, args: readonly string[]): { text: string; next?: ThemeFile } => {
  const [verb, a, b] = args
  if (verb === 'theme') {
    if (!a) return { text: show(now) }
    if (!PRESETS[a]) return { text: `No theme named "${a}". Available themes: ${Object.keys(PRESETS).join(', ')}` }
    const next = { preset: a, overrides: {} }
    return { text: show(next), next }
  }
  if (a === 'reset') {
    const next = { ...now, overrides: {} }
    return { text: show(next), next }
  }
  if (!a || !b || !SLOTS.includes(a as Slot) || !isColor(b)) {
    return { text: `Usage: color <${SLOTS.join('|')}> <#RRGGBB color code>, undo: color reset` }
  }
  const next = { ...now, overrides: { ...now.overrides, [a]: b } }
  return { text: show(next), next }
}
