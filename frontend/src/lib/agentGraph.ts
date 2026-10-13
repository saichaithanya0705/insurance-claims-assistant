import type { AgentInfo, GraphView } from './api'

// The LangGraph graphs the agents run in, ready to draw. The server reads them from the compiled graphs; this puts the
// stages in running order and names the agents in each. Pure, so it can be tested without a browser.

export interface StageBox {
  id: string
  /** The stage in words. */
  label: string
  /** The agents that work in this stage, by name; empty for the human gate. */
  agents: { id: string; name: string }[]
  /** More than one agent: they run side by side. */
  parallel: boolean
  human: boolean
}

const LABELS: Record<string, string> = {
  classify: 'Classify',
  retrieve: 'Gather evidence',
  investigate: 'Investigate',
  risk: 'Score risk',
  recommend: 'Recommend',
  validate: 'Check the brief',
  supervise: 'Supervisor review',
  judge: 'Independent review',
  review: 'Handler decides',
}

/** Node ids in the order the edges lead from the first to the last. A node no edge reaches is put at the end rather than lost. */
export function runningOrder(nodes: readonly { id: string }[], edges: readonly { from: string; to: string }[]): string[] {
  const ids = nodes.map((n) => n.id)
  const known = new Set(ids)
  // Only edges between the nodes themselves count: the graph's own start and end markers are not stages.
  const between = edges.filter((e) => known.has(e.from) && known.has(e.to))
  const next = new Map(between.map((e) => [e.from, e.to]))
  const reached = new Set(between.map((e) => e.to))
  const order: string[] = []
  let current: string | undefined = ids.find((id) => !reached.has(id)) ?? ids[0]
  while (current && !order.includes(current)) {
    order.push(current)
    current = next.get(current)
  }
  return [...order, ...ids.filter((id) => !order.includes(id))]
}

/** A sentence on the loop inside the supervise stage, built from its compiled graph; null when the graph has no send-back loop. */
export function superviseLine(graph: GraphView | undefined): string | null {
  if (!graph) return null
  const sendsBack = graph.edges.some((e) => e.from === 'review' && e.to === 'revise' && e.conditional)
  const returns = graph.edges.some((e) => e.from === 'revise' && e.to === 'review')
  if (!sendsBack || !returns) return null
  return 'Inside the Supervise stage there is a loop: the Supervisor reviews the brief and writes the summary. If the checks failed in a way that rewording can fix, it sends the findings back once, and the Investigation Agent, Risk Analyst, Recommendation Agent and Brief Validator redo their work; then it reviews again. Otherwise the brief goes on.'
}

export function stageBoxes(graph: GraphView, roster: readonly AgentInfo[]): StageBox[] {
  const names = new Map(roster.map((a) => [a.id, a.name]))
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  return runningOrder(graph.nodes, graph.edges).map((id) => {
    const agents = (byId.get(id)?.agents ?? []).map((agent) => ({ id: agent, name: names.get(agent) ?? agent }))
    return { id, label: LABELS[id] ?? id, agents, parallel: agents.length > 1, human: agents.length === 0 }
  })
}
