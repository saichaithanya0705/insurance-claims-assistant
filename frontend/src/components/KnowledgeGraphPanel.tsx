import type { GraphProcedure, KnowledgeGraph } from '../lib/api'
import { appliesLabel, callSummary, followUpLine, hitOutcome, shortChunk } from '../lib/graphView'

// Procedures, steps and linked rules are what Synapt extracted into its knowledge graph; the sentence of each step is
// Synapt's own text. The only rule that is ours is which procedures apply to the claim type, and it is shown.

function Procedure({ procedure, claimType, onOpen }: { procedure: GraphProcedure; claimType?: string | null; onOpen: (id: string) => void }) {
  return (
    <article className="kg-proc" data-testid="kg-procedure">
      <header className="kg-proc-head">
        <h4 className="kg-proc-name">{procedure.name}</h4>
        <span className="kg-proc-for">{appliesLabel(procedure.applies_because, claimType)}</span>
        {procedure.found_by === 'model' && <span className="kg-proc-for" data-testid="kg-model-found">Found by a model search</span>}
      </header>
      {procedure.intent && <p className="kg-proc-intent">{procedure.intent}</p>}
      <ol className="kg-steps" aria-label={`Steps of ${procedure.name}, in order`}>
        {[...procedure.steps].sort((a, b) => a.number - b.number).map((step) => (
          <li className="kg-step" key={step.number}>
            <span className="kg-step-no" aria-hidden="true">{step.number}</span>
            <div className="kg-step-body">
              <p className="kg-step-text">{step.text}</p>
              {(step.needs || step.who) && (
                <p className="kg-step-meta">
                  {step.needs && <span>Needs first: {step.needs}</span>}
                  {step.who && <span>Done by: {step.who}</span>}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
      {procedure.entities.length > 0 && (
        <div className="kg-links">
          <span className="kg-links-label">Linked in the graph</span>
          <ul>
            {procedure.entities.map((entity) => (
              <li key={entity.label} title={entity.description || undefined}>
                <span className="kg-kind">{entity.kind}</span> {entity.label}
              </li>
            ))}
          </ul>
        </div>
      )}
      <footer className="kg-proc-foot">
        {procedure.source_chunk_ids.length > 0 && (
          <span className="kg-source">Extracted from passage {procedure.source_chunk_ids.map(shortChunk).join(', ')}</span>
        )}
        <button type="button" className="btn kg-open" onClick={() => onOpen(procedure.source_id)}>
          Open as cited evidence
        </button>
      </footer>
    </article>
  )
}

export function KnowledgeGraphPanel({ graph, claimType, onOpen }: { graph?: KnowledgeGraph | null; claimType?: string | null; onOpen: (id: string) => void }) {
  // Runs saved before this panel existed, and runs that never reached Synapt, have no graph; the page omits it.
  if (!graph) return null
  if (!graph.available) {
    return (
      <p className="kg-unavailable" role="note">
        The Synapt knowledge graph was not read for this run{graph.reason ? `: ${graph.reason}` : '.'}
      </p>
    )
  }
  return (
    <section className="kg-panel" aria-labelledby="kg-heading">
      <h3 className="kg-heading" id="kg-heading">Handling procedures from the Synapt knowledge graph</h3>
      <p className="kg-desc">
        Synapt keeps the handling guidance it extracted from our documents as a graph: procedures linked to their ordered
        steps, to the rules they reference and to the passage each came from. For this claim the graph was searched by
        meaning, procedures written for other claim types were set aside, and each remaining procedure was walked step by
        step. These procedures are cited as evidence, and the handler decides what to request.
      </p>
      {graph.cues && graph.cues.length > 0 && (
        <p className="kg-cues" data-testid="kg-cues">
          <span className="kg-cues-label">This claim meets</span>
          {graph.cues.map((cue) => <span className="kg-cue" key={cue.key}>{cue.label}</span>)}
        </p>
      )}
      {graph.procedures.length === 0 ? (
        <p className="kg-empty">The graph returned no procedure with steps for this claim.</p>
      ) : (
        graph.procedures.map((procedure) => (
          <Procedure key={procedure.source_id} procedure={procedure} claimType={claimType} onOpen={onOpen} />
        ))
      )}
      <details className="kg-how">
        <summary>How these were found</summary>
        {graph.searches.map((search) => (
          <div className="kg-search" key={search.scope}>
            <p className="kg-search-query">Searched for: “{search.query}”</p>
            <ul>
              {search.found.map((hit) => (
                <li key={hit.name} className={hit.used ? 'kg-hit-used' : 'kg-hit-skipped'}>
                  <span>{hit.name}{typeof hit.score === 'number' ? ` · score ${hit.score.toFixed(2)}` : ''}</span>
                  <span className="kg-hit-outcome">{hitOutcome(hit)}</span>
                </li>
              ))}
              {search.found.length === 0 && <li className="kg-hit-skipped">Nothing found</li>}
            </ul>
          </div>
        ))}
        {followUpLine(graph) && <p className="kg-calls" data-testid="kg-followup">{followUpLine(graph)}</p>}
        <p className="kg-calls">{callSummary(graph)}</p>
      </details>
    </section>
  )
}
