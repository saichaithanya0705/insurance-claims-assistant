import type { RunAgent } from './api'

// A finished investigation drawn as one lane per agent. Pure, so it can be tested without a browser.

export interface Lane {
  id: string
  name: string
  method: string
  ran: boolean
  status: string
  background: boolean
  /** Position and length of the bar, in percent of the whole run (the bar is never narrower than a sliver, so a short step shows). */
  left: number
  width: number
  durationMs: number
  tokens: number
  toolLine: string
  toolsUsed: [string, number][]
  refused: string[]
}

export function swimlanes(agents: readonly RunAgent[]): Lane[] {
  const span = Math.max(1, ...agents.filter((a) => a.ran).map((a) => (a.started_ms ?? 0) + (a.duration_ms ?? 0)))
  return agents.map((a) => {
    const started = a.started_ms ?? 0
    const duration = a.duration_ms ?? 0
    const left = Math.min(98, Math.max(0, (started / span) * 100))
    const calls = a.tool_calls ?? 0
    const refused = a.refused ?? 0
    return {
      id: a.id,
      name: a.name,
      method: a.method,
      ran: a.ran,
      status: a.status ?? 'ok',
      background: a.background === true,
      left,
      width: Math.min(100 - left, Math.max(1.2, (duration / span) * 100)),
      durationMs: duration,
      tokens: a.tokens ?? 0,
      toolLine: (calls ? `${calls} tool ${calls === 1 ? 'call' : 'calls'}` : 'no tool calls') + (refused ? ` · ${refused} refused` : ''),
      toolsUsed: Object.entries(a.tools_used ?? {}).sort(([x], [y]) => x.localeCompare(y)),
      refused: refused ? (a.tools_refused ?? []) : [],
    }
  })
}
