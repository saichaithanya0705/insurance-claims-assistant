import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { RunPreview } from '../lib/api'
import { previewParts, queryLine } from '../lib/preview'
import { Card } from './ui'

// The parts of an investigation that have finished, shown while the rest is still running. Each section appears when its
// stage has saved what it produced (the server sends nothing that has not landed). Nothing here is the brief: it is not
// complete, not validated and not reviewed until the run ends, and the panel says so.

/** Poll the run's preview until the component goes away (the page swaps in the finished run). */
function usePreview(runId: string): RunPreview | null {
  const [preview, setPreview] = useState<RunPreview | null>(null)
  useEffect(() => {
    let stopped = false
    const controller = new AbortController()
    const tick = async () => {
      try {
        const latest = await api<RunPreview>(`/api/investigations/${encodeURIComponent(runId)}/preview`, { signal: controller.signal, timeoutMs: 6000 })
        if (!stopped) setPreview(latest)
      } catch {
        /* the run may not be saved yet, or a poll was cut off: the next one will do */
      }
    }
    tick()
    const timer = window.setInterval(tick, 1500)
    return () => {
      stopped = true
      controller.abort()
      window.clearInterval(timer)
    }
  }, [runId])
  return preview
}

export function BriefPreviewView({ preview, admin }: { preview: RunPreview | null; admin: boolean }) {
  const parts = previewParts(preview)
  if (!preview || !parts.length) return null
  return (
    <Card className="preview-card">
      <div className="card-body">
        <h3 className="preview-title">Coming together</h3>
        <p className="preview-note">Parts of the brief appear here as they finish. This is not the brief yet: it has not been completed, checked or reviewed.</p>
        {parts.map((part) => (
          <section key={part.key} className="preview-part" aria-label={part.title}>
            <h4>{part.title}</h4>
            {part.key === 'search' && preview.retrieval && (
              <>
                <p className="preview-line">{part.summary}</p>
                {preview.retrieval.procedures.length > 0 && (
                  <ul className="preview-chips" aria-label="Procedures found">
                    {preview.retrieval.procedures.map((name) => <li key={name}>{name}</li>)}
                  </ul>
                )}
                {preview.retrieval.cohort && <p className="preview-line">{preview.retrieval.cohort}</p>}
                {preview.retrieval.similar_cases.length > 0 && (
                  <ul className="preview-list" aria-label="Closest past claims">
                    {preview.retrieval.similar_cases.map((c, i) => (
                      <li key={i}>{`${c.claim_type ?? 'claim'} in ${c.state ?? '—'}, $${Math.round(Number(c.claim_amount) || 0).toLocaleString('en-US')}, ${c.claim_status ?? ''}${c.days_to_resolution != null ? ` in ${Math.round(Number(c.days_to_resolution))} days` : ''}`}</li>
                    ))}
                  </ul>
                )}
                {preview.retrieval.query_agent && <p className="preview-line preview-muted">{queryLine(preview.retrieval.query_agent, admin)}</p>}
              </>
            )}
            {part.key === 'findings' && preview.findings && (
              <ul className="preview-list">
                {preview.findings.map((f, i) => <li key={i}><b className="preview-kind">{f.kind}</b> {f.text}</li>)}
              </ul>
            )}
            {part.key === 'priority' && preview.priority && (
              <>
                <p className="preview-line">{part.summary}</p>
                {preview.priority.reasons.length > 0 && <ul className="preview-list">{preview.priority.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
              </>
            )}
            {part.key === 'recommendations' && preview.recommendations && (
              <ul className="preview-list">
                {preview.recommendations.map((r, i) => <li key={i}><b>{r.action}</b>{r.reason ? `: ${r.reason}` : ''}</li>)}
              </ul>
            )}
          </section>
        ))}
      </div>
    </Card>
  )
}

export function BriefPreview({ runId, admin }: { runId: string; admin: boolean }) {
  return <BriefPreviewView preview={usePreview(runId)} admin={admin} />
}
