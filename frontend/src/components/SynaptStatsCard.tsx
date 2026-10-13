import { useEffect, useRef, useState } from 'react'
import { Database } from 'lucide-react'
import { api, type SynaptStats } from '../lib/api'
import { statNote, statTiles } from '../lib/synaptStats'
import { Card } from './ui'

/** What the knowledge base holds right now: the numbers a reviewer would otherwise have to look up in Synapt itself. */
export function SynaptStatsView({ stats, loading }: { stats: SynaptStats | null; loading: boolean }) {
  return (
    <Card>
      <div className="card-head">
        <h2>
          <span className="head-icon">
            <Database size={15} />
          </span>
          Knowledge base contents
        </h2>
        <span className="step-tag">{stats?.provider_id ?? 'Synapt'}</span>
      </div>
      <div className="card-body">
        {!stats ? (
          loading ? <div className="skeleton" aria-label="Loading knowledge base contents" style={{ height: 120 }} /> : <p className="small-empty">Knowledge base contents are unavailable.</p>
        ) : !stats.available ? (
          <p className="small-empty">{stats.reason ?? 'Knowledge base contents are unavailable.'}</p>
        ) : (
          <>
            <div className="status-grid stats-grid">
              {statTiles(stats).map((tile) => (
                <div className="status-tile" key={tile.label} title={tile.hint}>
                  <small>{tile.label}</small>
                  <b className="stat-value">{tile.value}</b>
                </div>
              ))}
            </div>
            {!!stats.knowledge_by_kind?.length && (
              <div className="stat-kinds" aria-label="Knowledge extracted by kind">
                {stats.knowledge_by_kind.map((k) => (
                  <span className="stat-kind" key={k.kind}>
                    {k.kind} <b>{k.count.toLocaleString('en-US')}</b>
                  </span>
                ))}
              </div>
            )}
            <p className="footnote">{statNote(stats)}</p>
          </>
        )}
      </div>
    </Card>
  )
}

/** Loads the figures separately from the connection status, so a slow read never holds the rest of the page back. */
export function SynaptStatsCard({ reload }: { reload: number }) {
  const [stats, setStats] = useState<SynaptStats | null>(null)
  const [loading, setLoading] = useState(true)
  const request = useRef(0)

  useEffect(() => {
    const id = ++request.current
    api<SynaptStats>(`/api/integration/synapt-stats${reload > 0 ? '?refresh=true' : ''}`)
      .then((result) => {
        if (id === request.current) setStats(result)
      })
      .catch(() => {
        if (id === request.current) setStats({ available: false, reason: 'The knowledge base summary could not be loaded.' })
      })
      .finally(() => {
        if (id === request.current) setLoading(false)
      })
    return () => {
      request.current += 1
    }
  }, [reload])

  return <SynaptStatsView stats={stats} loading={loading} />
}
