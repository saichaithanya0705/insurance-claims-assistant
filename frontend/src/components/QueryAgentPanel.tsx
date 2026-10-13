import type { Evidence, QueryAgent } from '../lib/api'
import { FeedbackBar } from './FeedbackBar'
import { PartView } from './SideChat'

// Synapt's query agent's answer to the one fixed handling question every investigation asks. It is shown so a reader can
// compare it with the brief, and so the same call can be found in Synapt's Explainability. It is display only: the brief's
// findings never cite it and the brief's validation never checks it, because it is text a model wrote.

export function QueryAgentPanel({ queryAgent, admin, evidence, onOpen, runId }: { queryAgent?: QueryAgent | null; admin: boolean; evidence: Evidence[]; onOpen: (id: string) => void; runId?: string }) {
  // Runs saved before this panel existed, and runs that made no call (evaluation, degraded), have none; the page omits it.
  if (!queryAgent) return null
  const who = admin ? 'Synapt query agent' : 'Knowledge base'
  if (queryAgent.pending) {
    return (
      <section className="qa-panel qa-waiting" aria-labelledby="qa-heading" aria-busy="true">
        <h3 className="qa-heading" id="qa-heading">{who}: how to handle this kind of claim</h3>
        <p className="qa-desc">
          {admin ? 'Synapt’s query agent' : 'The knowledge base'} is still writing its answer. The brief did not wait for it, and it will appear here as soon as it is ready.
        </p>
        <div className="qa-asked">
          <span className="qa-asked-label">What was asked</span>
          <p className="qa-question">{queryAgent.question}</p>
        </div>
      </section>
    )
  }
  if (!queryAgent.available || !queryAgent.part) {
    return (
      <p className="qa-unavailable" role="note">
        {who} did not answer for this run{queryAgent.reason ? `: ${queryAgent.reason}` : '.'} The brief does not depend on it.
      </p>
    )
  }
  return (
    <section className="qa-panel" aria-labelledby="qa-heading">
      <h3 className="qa-heading" id="qa-heading">{who}: how to handle this kind of claim</h3>
      <p className="qa-desc">
        {admin ? 'Synapt’s query agent' : 'The knowledge base'} was asked one fixed question about this claim type, and answered from its own passages, procedures and
        graph. It is shown beside the brief for comparison. The brief’s findings do not use it and its validation does not check it.
      </p>
      <div className="qa-asked">
        <span className="qa-asked-label">What was asked</span>
        <p className="qa-question">{queryAgent.question}</p>
        <p className="qa-sent">Sent: the claim type only. The description, names, amounts and dates never leave this application.</p>
      </div>
      <PartView part={queryAgent.part} admin={admin} evidence={evidence} onOpen={onOpen} />
      {runId && <FeedbackBar runId={runId} target="investigation" admin={admin} />}
      {admin && queryAgent.task_id && queryAgent.part.synapt?.query_id && (
        <div className="qa-find">
          <span className="qa-asked-label">Find this call in Synapt</span>
          <p>
            Explainability, then search for query ID <code className="qa-id">{queryAgent.part.synapt.query_id}</code>. Its task ID is this run’s ID,{' '}
            <code className="qa-id">{queryAgent.task_id}</code>.
          </p>
        </div>
      )}
    </section>
  )
}
