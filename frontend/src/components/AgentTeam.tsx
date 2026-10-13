import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, BadgeCheck, BookOpen, Check, CircleDashed, Database, Gavel, Hourglass, Loader2, Network, Route, Scale, Search, ShieldCheck, Sparkles, Wrench } from 'lucide-react'
import { api } from '../lib/api'
import type { AgentInfo, AgentRoster } from '../lib/api'
import { agentCards, canUseLine, methodWord, STATE_WORDS, teamSummary } from '../lib/agentTeam'
import type { AgentCard, AgentState } from '../lib/agentTeam'
import { cx } from '../lib/format'
import type { LiveView } from '../lib/liveProgress'
import { formatDuration } from '../lib/trace'

// The agents of the investigation, shown while it runs. Each card is driven by the spans its agent really opened (the server
// stamps every step with the agent that took it), so a card says "working" only while that agent has a step open, and the
// agents that gather evidence at the same moment really are shown working together.

const ICONS: Record<string, typeof Route> = {
  triage: Route,
  passage_retriever: BookOpen,
  graph_navigator: Network,
  knowledge_qa: Sparkles,
  history_analyst: Database,
  investigator: Search,
  risk_analyst: Scale,
  recommender: Wrench,
  validator: ShieldCheck,
  supervisor: BadgeCheck,
  judge: Gavel,
}

const STAGE_TAGS: Record<string, string> = {
  classify: 'Classify',
  retrieve: 'Gather evidence',
  investigate: 'Investigate',
  risk: 'Score risk',
  recommend: 'Recommend',
  validate: 'Check',
  supervise: 'Supervise',
  judge: 'Review',
}

export const agentIcon = (id: string) => ICONS[id] ?? Route

let rosterRequest: Promise<AgentInfo[]> | null = null

/** The roster, fetched once per page load (it changes only when the application does). null while loading or if it cannot be read. */
export function useAgentRoster(): AgentInfo[] | null {
  const [roster, setRoster] = useState<AgentInfo[] | null>(null)
  useEffect(() => {
    let alive = true
    rosterRequest ??= api<AgentRoster>('/api/agents', { timeoutMs: 8000 }).then((r) => r.agents)
    rosterRequest.then((agents) => alive && setRoster(agents)).catch(() => { rosterRequest = null })
    return () => { alive = false }
  }, [])
  return roster
}

export function StateIcon({ state, size = 15 }: { state: AgentState; size?: number }) {
  if (state === 'working' || state === 'background') return <Loader2 size={size} className="spin" aria-hidden="true" />
  if (state === 'done') return <Check size={size} aria-hidden="true" />
  if (state === 'failed') return <AlertTriangle size={size} aria-hidden="true" />
  if (state === 'skipped') return <CircleDashed size={size} aria-hidden="true" />
  return <Hourglass size={size} aria-hidden="true" />
}

function Card({ card }: { card: AgentCard }) {
  const { agent, state } = card
  const Icon = agentIcon(agent.id)
  const line = card.doing ?? card.result ?? STATE_WORDS[state]
  return (
    <li className={cx('agent-card', state)} data-testid="agent-card" data-agent={agent.id} data-state={state}>
      <div className="agent-top">
        <span className="agent-ico"><Icon size={16} aria-hidden="true" /></span>
        <strong className="agent-name">{agent.name}</strong>
        {card.elapsedMs !== null && <span className="agent-time">{formatDuration(card.elapsedMs)}</span>}
        <span className="agent-state" title={STATE_WORDS[state]}><StateIcon state={state} size={14} /><span className="sr-only">{STATE_WORDS[state]}</span></span>
      </div>
      <p className="agent-tag">{STAGE_TAGS[agent.stage] ?? agent.stage} · {methodWord(agent)}</p>
      <p className="agent-role" title={agent.purpose}>{agent.purpose}</p>
      <p className="agent-doing" data-testid="agent-doing">{line}{state === 'background' ? ' · in the background' : ''}</p>
      <p className="agent-tools">{canUseLine(agent)}</p>
    </li>
  )
}

/** The panel. Pure: the view, the roster and the clock come in as props, so it renders the same way in a test. */
export function AgentTeamView({ view, roster, now }: { view: LiveView; roster: readonly AgentInfo[]; now: number }) {
  const cards = useMemo(() => agentCards(view, roster, now), [view, roster, now])
  const { working, done, total } = teamSummary(cards)
  if (cards.length === 0) return null
  return (
    <section className="agent-team" aria-label="The agents working on this investigation" data-testid="agent-team">
      <header className="agent-team-head">
        <h3>The agent team</h3>
        <p role="status">{working > 0 ? `${working} working now · ` : ''}{done} of {total} done</p>
      </header>
      <ol className="agent-grid">
        {cards.map((card) => <Card key={card.agent.id} card={card} />)}
      </ol>
      <p className="live-note">Each agent has a written role and a short list of tools it may use; anything outside its list is refused. Agents that gather evidence run at the same time.</p>
    </section>
  )
}
