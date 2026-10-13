import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowRight, Check, Minus } from 'lucide-react'
import { api } from '../lib/api'
import type { AgentGraphs, AgentInfo, AgentRoster, RunAgent } from '../lib/api'
import { canUseLine, methodWord } from '../lib/agentTeam'
import { swimlanes } from '../lib/agentLanes'
import { stageBoxes, superviseLine } from '../lib/agentGraph'
import { cx } from '../lib/format'
import { formatDuration } from '../lib/trace'
import { agentIcon } from './AgentTeam'
import { Card } from './ui'

// Who does what: the agents of an investigation, their written roles and the tools each may use. Everyone sees names, purposes
// and what each agent can use, in plain words. Administrators also see the tool IDs, the identity each agent presents, the role
// prompt it is given and the access matrix: which agent may call which tool (anything not marked is refused on every call).

function AgentCard({ agent, admin }: { agent: AgentInfo; admin: boolean }) {
  const Icon = agentIcon(agent.id)
  return (
    <li className="agent-card static" data-testid="agent-profile" data-agent={agent.id}>
      <div className="agent-top">
        <span className="agent-ico"><Icon size={16} aria-hidden="true" /></span>
        <strong className="agent-name">{agent.name}</strong>
      </div>
      <p className="agent-tag">{agent.kind === 'agent' ? `${agent.stage} · ${methodWord(agent)}` : agent.kind === 'human' ? 'Person' : 'Not part of an investigation'}</p>
      <p className="agent-role full">{agent.purpose}</p>
      <p className="agent-tools">{canUseLine(agent)}</p>
      {agent.cannot && <p className="agent-tools">Cannot: {agent.cannot}</p>}
      {admin && (
        <details className="agent-admin">
          <summary>Technical details</summary>
          <dl>
            <dt>Identity</dt><dd><code>{agent.identity}</code></dd>
            {agent.tools?.some((t) => t.startsWith('trident_')) && <><dt>Connector client ID</dt><dd>{agent.client_id_set ? 'set in configuration (not used to sign in yet)' : 'not set'}</dd></>}
            <dt>Tools</dt><dd>{agent.tools?.length ? agent.tools.map((t) => <code key={t}>{t}</code>) : 'none'}</dd>
            {agent.model_purpose && <><dt>Model setting</dt><dd><code>{agent.model_purpose}</code></dd></>}
          </dl>
          {agent.prompt && <><p className="agent-prompt-label">Role prompt (before the rules every agent follows)</p><pre className="agent-prompt">{agent.prompt}</pre></>}
        </details>
      )}
    </li>
  )
}

/** The graph the agents run in, drawn from the compiled LangGraph graphs: one box per stage, in running order, with the agents
 *  that work in it. The retrieve stage is a graph of its own whose four agents run side by side. */
function AgentGraph({ graphs, roster, admin }: { graphs: AgentGraphs; roster: readonly AgentInfo[]; admin: boolean }) {
  const boxes = stageBoxes(graphs.investigation, roster)
  const inner = new Map(stageBoxes(graphs.retrieve, roster).map((b) => [b.id, b]))
  return (
    <Card spot={false} className="agent-graph-card" data-testid="agent-graph">
      <h2>How the agents are wired</h2>
      <p className="subtitle">The investigation is a LangGraph graph with one step per stage. Most steps are one agent; gathering evidence is a graph of its own in which four agents work side by side before their findings are joined. This is read from the compiled graphs, not drawn by hand.</p>
      <ol className="flow" aria-label="Stages of an investigation">
        {boxes.map((box, index) => (
          <li key={box.id} className={cx('flow-step', box.parallel && 'parallel', box.human && 'human')} data-stage={box.id}>
            <div className="flow-box">
              <strong>{box.label}</strong>
              {box.human ? (
                <span className="flow-agent person">A person decides (the graph pauses here)</span>
              ) : (
                <ul>
                  {box.agents.map((agent) => (
                    <li key={agent.id} className="flow-agent">{agent.name}</li>
                  ))}
                </ul>
              )}
              {box.parallel && <small>{box.agents.length} agents at the same time, then their findings are joined</small>}
            </div>
            {index < boxes.length - 1 && <ArrowRight size={16} className="flow-arrow" aria-hidden="true" />}
          </li>
        ))}
      </ol>
      {superviseLine(graphs.supervise) && <p className="live-note" data-testid="supervise-loop">{superviseLine(graphs.supervise)}</p>}
      {admin && (
        <details className="agent-admin">
          <summary>LangGraph graphs as Mermaid text</summary>
          <p className="agent-prompt-label">Investigation graph</p>
          <pre className="agent-prompt">{graphs.investigation.mermaid}</pre>
          <p className="agent-prompt-label">Retrieve stage graph ({inner.size} nodes)</p>
          <pre className="agent-prompt">{graphs.retrieve.mermaid}</pre>
          {graphs.supervise && <><p className="agent-prompt-label">Supervise stage graph</p><pre className="agent-prompt">{graphs.supervise.mermaid}</pre></>}
        </details>
      )}
    </Card>
  )
}

function AccessMatrix({ roster }: { roster: AgentRoster }) {
  const tools = roster.tools ?? []
  const columns = roster.agents
  return (
    <Card spot={false} className="agent-matrix-card">
      <h2>Who may call what</h2>
      <p className="subtitle">A mark means that actor holds the tool. Every other call is refused when it is made, and the refusal is recorded in the trace. Marks in the last three columns belong to actors outside the investigation.</p>
      <div className="agent-matrix-scroll" tabIndex={0} role="region" aria-label="Tool access by agent">
        <table className="agent-matrix">
          <thead>
            <tr>
              <th scope="col">Tool</th>
              {columns.map((a) => <th key={a.id} scope="col" className={cx(a.kind !== 'agent' && 'outside')}><span>{a.name}</span></th>)}
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => (
              <tr key={tool.id} className={cx(tool.writes && 'writes')}>
                <th scope="row"><code>{tool.id}</code><small>{tool.plain}{tool.writes ? ' · writes' : ''}</small></th>
                {columns.map((a) => {
                  const held = tool.held_by.includes(a.id)
                  return (
                    <td key={a.id} className={cx(held && 'held', a.kind !== 'agent' && 'outside')} data-held={held}>
                      {held ? <><Check size={14} aria-hidden="true" /><span className="sr-only">{a.name} may call {tool.id}</span></> : <><Minus size={12} aria-hidden="true" /><span className="sr-only">no</span></>}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export function AgentsView({ admin }: { admin: boolean }) {
  const [roster, setRoster] = useState<AgentRoster | null>(null)
  const [graphs, setGraphs] = useState<AgentGraphs | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    api<AgentRoster>('/api/agents', { signal: controller.signal })
      .then((r) => !controller.signal.aborted && setRoster(r))
      .catch((e) => !controller.signal.aborted && setError((e as Error).message))
    api<AgentGraphs>('/api/agents/graph', { signal: controller.signal })
      .then((g) => !controller.signal.aborted && setGraphs(g))
      .catch(() => undefined) // the diagram is a convenience; the cards below do not depend on it
    return () => controller.abort()
  }, [])
  const team = roster?.agents.filter((a) => a.kind === 'agent') ?? []
  const others = roster?.agents.filter((a) => a.kind !== 'agent') ?? []
  return (
    <motion.section aria-labelledby="agents-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Who does what</div>
          <h1 id="agents-title" className="display" tabIndex={-1}>Agents</h1>
          <p className="subtitle">Every investigation is done by eleven named agents. Each has a written role and a short list of tools it may use; the agents that write the findings and recommendations reason over evidence and hold no tools. Only the three retrieval agents can read the knowledge base: each runs its standard search, then lets a model decide on one round of follow-up, checked before anything is sent.</p>
        </div>
      </div>
      {error && <p className="error-box" role="alert">{error}</p>}
      {!roster && !error && <p className="live-note">Loading the agents…</p>}
      {roster && (
        <>
          {graphs && <AgentGraph graphs={graphs} roster={roster.agents} admin={admin} />}
          <ol className="agent-grid roster" aria-label="The investigation team">
            {team.map((a) => <AgentCard key={a.id} agent={a} admin={admin} />)}
          </ol>
          {admin && <AccessMatrix roster={roster} />}
          {admin && others.length > 0 && (
            <>
              <h2 className="agents-sub">Other actors that can reach the knowledge base</h2>
              <p className="subtitle">None of these is an investigation agent. The operator only reads, the ingestion job is the only actor that writes documents, and the person who rates an answer is the only one who can send feedback.</p>
              <ol className="agent-grid roster" aria-label="Other actors">
                {others.map((a) => <AgentCard key={a.id} agent={a} admin={admin} />)}
              </ol>
            </>
          )}
        </>
      )}
    </motion.section>
  )
}

/** One finished investigation read agent by agent: a lane for each, so the agents that worked at the same time can be seen to. */
export function RunAgents({ runId, admin }: { runId: string; admin: boolean }) {
  const [agents, setAgents] = useState<RunAgent[] | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    api<{ agents: RunAgent[] }>(`/api/investigations/${encodeURIComponent(runId)}/agents`, { signal: controller.signal })
      .then((r) => !controller.signal.aborted && setAgents(r.agents))
      .catch(() => !controller.signal.aborted && setAgents([]))
    return () => controller.abort()
  }, [runId])
  const lanes = agents ? swimlanes(agents) : []
  if (!agents || lanes.every((l) => !l.ran)) return null
  return (
    <Card spot={false} className="run-agents" data-testid="run-agents">
      <h2>Who did the work</h2>
      <p className="subtitle">Each lane is one agent, drawn from the steps it really took, so agents that worked together appear side by side.</p>
      <ol className="lanes">
        {lanes.map((lane) => (
          <li key={lane.id} className={cx('lane', !lane.ran && 'idle', lane.status === 'error' && 'bad')} data-agent={lane.id}>
            <div className="lane-name">
              <strong>{lane.name}</strong>
              <small>{lane.ran ? [lane.method === 'model' ? 'language model' : 'fixed rules', lane.toolLine, lane.tokens ? `${lane.tokens.toLocaleString('en-US')} tokens` : ''].filter(Boolean).join(' · ') : 'did not run'}</small>
            </div>
            <div className="lane-track" aria-hidden="true">
              {lane.ran && <i style={{ left: `${lane.left}%`, width: `${lane.width}%` }} className={cx(lane.background && 'background')} />}
            </div>
            <span className="lane-time">{lane.ran ? formatDuration(lane.durationMs) : '—'}</span>
            {admin && lane.ran && (lane.toolsUsed.length > 0 || lane.refused.length > 0) && (
              <p className="lane-tools">
                {lane.toolsUsed.map(([tool, n]) => <code key={tool}>{tool} ×{n}</code>)}
                {lane.refused.map((tool) => <code key={tool} className="refused">{tool} refused</code>)}
              </p>
            )}
          </li>
        ))}
      </ol>
    </Card>
  )
}
