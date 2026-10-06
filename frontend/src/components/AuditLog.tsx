import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { label } from '../lib/format'
import { DataView, ErrorBox } from './ui'

interface AuditPage { items: { id: number; time: string; kind: string; body: unknown }[]; total: number; offset: number; limit: number }
export function AuditLog({ runId }: { runId: string }) {
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<AuditPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api<AuditPage>(`/api/investigations/${encodeURIComponent(runId)}/audit?offset=${offset}`, { signal: controller.signal }).then(result => {
      if (!Array.isArray(result.items) || !Number.isInteger(result.total)) throw new Error('Audit log is invalid.')
      if (!controller.signal.aborted) setPage(result)
    }).catch(e => { if (!controller.signal.aborted) setError(e.message) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [runId, offset, retry])
  const move = (next: number) => { setLoading(true); setError(null); setOffset(next) }
  return <details className="disclose"><summary>Detailed request log · Prompts, validated outputs and decisions</summary><p className="footnote">Administrator access. Original saved audit events; generated content remains subject to evidence and validation checks.</p><ErrorBox message={error} />{error && <button className="btn" onClick={() => { setLoading(true); setError(null); setRetry(n => n + 1) }}>Retry log</button>}<p role="status">{loading ? 'Loading request log…' : !error ? `${page?.total ?? 0} saved events` : ''}</p>{!loading && !error && page?.items.map(event => <details className="disclose" key={event.id}><summary>{label(event.kind)} · {new Date(event.time).toLocaleString()}</summary><DataView value={event.body} /></details>)}{page && page.total > page.limit && <div className="case-tools"><button className="btn" disabled={loading || offset === 0} onClick={() => move(Math.max(0, offset - page.limit))}>Previous events</button><button className="btn" disabled={loading || offset + page.limit >= page.total} onClick={() => move(offset + page.limit)}>Next events</button></div>}</details>
}
