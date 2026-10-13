import type { AgentInfo, LiveSpan } from './api'
import { elapsedMs } from './liveProgress'
import type { LiveView } from './liveProgress'

// The agents of an investigation, as they work. Plain functions so they can be tested without a browser. Nothing is staged:
// an agent is "working" only while a span it really opened is still running, and "done" only after that span closed.

/** waiting: has not started. working: a span of its own is open. done / failed: its spans closed. background: working on
 *  something nobody waits for. skipped: the run ended without it (for example the independent review is switched off). */
export type AgentState = 'waiting' | 'working' | 'done' | 'failed' | 'background' | 'skipped'

export interface AgentCard {
  agent: AgentInfo
  state: AgentState
  /** How long it has been working or took, on the server's clock carried forward by the browser's; null before it starts. */
  elapsedMs: number | null
  /** What it is doing right now (its newest open step), or null. */
  doing: string | null
  /** The server's one-line summary once it is done ("3 tool calls"). */
  result: string | null
  /** Steps it has taken so far (tool calls, model calls, searches), refused calls not counted. */
  steps: number
}

/** The agents that take part in an investigation, in the order they appear in the roster. */
export const teamOf = (roster: readonly AgentInfo[]): AgentInfo[] => roster.filter((a) => a.kind === 'agent')

export function agentCards(view: LiveView, roster: readonly AgentInfo[], clockNow: number): AgentCard[] {
  const spans = [...view.spans.values()]
  const ended = view.state === 'done' || view.state === 'failed'
  return teamOf(roster).map((agent) => {
    const mine = spans.filter((s) => s.agent === agent.id)
    const own = mine.filter((s) => s.kind === 'agent')
    const work = mine.filter((s) => s.kind !== 'agent' && s.name !== 'access.denied' && s.label !== 'Access denied')
    if (own.length === 0) {
      return { agent, state: ended ? 'skipped' : 'waiting', elapsedMs: null, doing: null, result: null, steps: 0 }
    }
    const running = own.filter((s) => s.status === 'running')
    const failed = own.some((s) => s.status === 'error')
    const background = own.some((s) => s.background)
    const start = Math.min(...own.map((s) => s.started_ms))
    const end = Math.max(...own.map((s) => s.started_ms + elapsedMs(s, view, clockNow)))
    const open = work.filter((s) => s.status === 'running').sort((a, b) => b.started_ms - a.started_ms)[0]
    const done = running.length === 0
    return {
      agent,
      state: done ? (failed ? 'failed' : 'done') : background ? 'background' : 'working',
      elapsedMs: Math.max(0, end - start),
      doing: done ? null : (open?.label ?? null),
      result: done ? (own.find((s) => s.result)?.result ?? null) : null,
      steps: work.length,
    }
  })
}

/** Counts for the heading: how many are working now and how many have finished. */
export function teamSummary(cards: readonly AgentCard[]): { working: number; done: number; total: number } {
  return {
    working: cards.filter((c) => c.state === 'working' || c.state === 'background').length,
    done: cards.filter((c) => c.state === 'done').length,
    total: cards.filter((c) => c.state !== 'skipped').length,
  }
}

export const STATE_WORDS: Record<AgentState, string> = {
  waiting: 'Waiting',
  working: 'Working',
  done: 'Done',
  failed: 'Failed',
  background: 'In the background',
  skipped: 'Did not run',
}

/** What an agent can use, as one short line: the plain tool names, or that it holds none. */
export function canUseLine(agent: AgentInfo): string {
  return agent.can_use.length ? `Can use: ${agent.can_use.join(', ')}` : 'Holds no tools'
}

export const methodWord = (agent: AgentInfo): string =>
  agent.method === 'model' ? 'Language model' : agent.method === 'rules' ? 'Fixed rules' : 'Not an agent'

/** The span an agent's open step belongs to, for tests and for a tooltip. */
export const openStepOf = (spans: Iterable<LiveSpan>, agentId: string): LiveSpan | undefined =>
  [...spans].filter((s) => s.agent === agentId && s.kind !== 'agent' && s.status === 'running').sort((a, b) => b.started_ms - a.started_ms)[0]
