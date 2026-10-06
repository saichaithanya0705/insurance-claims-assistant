import { motion } from 'motion/react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { KeyRound, Network, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, hasApiKey, setApiKey, type Health, type IntegrationStatus, type ModelStatus } from '../lib/api'
import { label } from '../lib/format'
import { Card, ErrorBox, Pill, useToast } from './ui'

const TONE = { teal: 'var(--teal)', amber: 'var(--amber)', violet: 'var(--violet)', sky: 'var(--sky)', rose: 'var(--rose)', slate: 'var(--text-3)' }
type Tone = keyof typeof TONE

function Node({ x, y, w, h, title, sub, tone }: { x: number; y: number; w: number; h: number; title: string; sub: string; tone: Tone; delay: number }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={6} fill="var(--surface-solid)" stroke="var(--border-strong)" />
      <circle cx={x + 16} cy={y + h / 2} r={4} fill={TONE[tone]} />
      <text x={x + 30} y={y + h / 2 - 3} fill="var(--text)" fontSize="13" fontWeight="600">{title}</text>
      <text x={x + 30} y={y + h / 2 + 13} fill="var(--text-2)" fontSize="12">{sub}</text>
    </g>
  )
}

function Link({ d, tone }: { d: string; tone: Tone; delay: number }) {
  return <path d={d} fill="none" stroke={TONE[tone]} strokeWidth={1.5} opacity={0.65} />
}

export function ConnectionView({ health, onHealthRefresh }: { health: Health | null; onHealthRefresh: () => void }) {
  const toast = useToast()
  const [status, setStatus] = useState<IntegrationStatus | null>(null)
  const [models, setModels] = useState<ModelStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [key, setKey] = useState('')
  const [keyApplied, setKeyApplied] = useState(hasApiKey())
  const refreshRequest = useRef(0)

  const refresh = useCallback(async () => {
    const request = ++refreshRequest.current
    setLoading(true)
    setError(null)
    try {
      const [integration, modelStatus] = await Promise.all([api<IntegrationStatus>('/api/integration/status'), api<ModelStatus>('/api/models/status').catch(() => null)])
      if (request !== refreshRequest.current) return
      setStatus(integration)
      setModels(modelStatus)
    } catch (e) {
      if (request !== refreshRequest.current) return
      setStatus(null)
      setModels(null)
      setError((e as Error).message)
    } finally {
      if (request === refreshRequest.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    return () => { refreshRequest.current += 1 }
  }, [refresh])

  const applyKey = (e: FormEvent) => {
    e.preventDefault()
    setApiKey(key.trim())
    setKeyApplied(key.trim().length > 0)
    setKey('')
    toast('Application key applied for this tab.')
    refresh()
    onHealthRefresh()
  }
  const clearKey = () => {
    setApiKey('')
    setKeyApplied(false)
    toast('Application key cleared.', 'info')
    refresh()
    onHealthRefresh()
  }

  const synaptTone: Tone = status?.mode === 'live' ? (status.live_verified ? 'teal' : 'amber') : 'violet'
  const agentTone: Tone = health?.agent_mode === 'live' ? 'teal' : 'violet'
  const historyTone: Tone = status?.local_history_origin === 'published_synthetic_dataset' ? 'teal' : 'amber'
  const modelTone: Tone = models?.available ? 'teal' : 'slate'
  const right = [
    { y: 26, title: 'Evidence retrieval', sub: status ? (status.mode === 'live' ? (status.live_verified ? 'Live · verified' : 'Live · unverified') : 'Synthetic evidence') : '…', tone: synaptTone },
    { y: 96, title: 'Brief preparation', sub: health ? label(health.agent_mode) : '…', tone: agentTone },
    { y: 166, title: 'Historical index', sub: status ? (status.local_history_origin === 'published_synthetic_dataset' ? 'Published synthetic' : label(status.local_history_origin)) : '…', tone: historyTone },
    { y: 236, title: 'Statistical models', sub: models ? (models.available ? 'Trained' : 'Not trained') : '…', tone: modelTone },
  ]

  return (
    <motion.section aria-labelledby="connection-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Shared knowledge layer</div>
          <h1 id="connection-title" className="display" tabIndex={-1}>
            Connection settings
          </h1>
          <p className="subtitle">Inspect integration readiness and the services used for evidence retrieval.</p>
        </div>
        <button className="btn" onClick={() => (refresh(), onHealthRefresh())} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : undefined} /> Refresh status
        </button>
      </div>
      {error && (
        <div style={{ marginBottom: 18 }}>
          <ErrorBox message={error} />
        </div>
      )}

      <Card>
        <div className="card-head">
          <h2>
            <span className="head-icon">
              <Network size={15} />
            </span>
            Service architecture
          </h2>
          <span className="step-tag">REQUEST FLOW</span>
        </div>
        <div className="card-body" style={{ overflowX: 'auto' }}>
          <svg className="arch" viewBox="0 0 780 300" role="img" aria-label="Request flow: browser to application service to investigation workflow, which retrieves evidence, prepares the brief, compares history and estimates outcomes" style={{ minWidth: 640 }}>
            <Link d="M150 150 H200" tone="sky" delay={0.2} />
            <Link d="M330 150 H380" tone="sky" delay={0.35} />
            {right.map((n, i) => (
              <Link key={n.title} d={`M510 150 C 550 150, 550 ${n.y + 22}, 590 ${n.y + 22}`} tone={n.tone} delay={0.5 + i * 0.1} />
            ))}
            <Node x={20} y={128} w={130} h={44} title="Browser UI" sub="React + Motion" tone="sky" delay={0.05} />
            <Node x={200} y={128} w={130} h={44} title="Application" sub={health ? `Status ${label(health.status)}` : '…'} tone={health?.status === 'ok' ? 'teal' : 'amber'} delay={0.15} />
            <Node x={380} y={128} w={130} h={44} title="Investigation" sub="7-stage workflow" tone="teal" delay={0.25} />
            {right.map((n, i) => (
              <Node key={n.title} x={590} y={n.y} w={170} h={44} title={n.title} sub={n.sub} tone={n.tone} delay={0.4 + i * 0.1} />
            ))}
          </svg>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-3)', marginTop: 10 }}>
            <span>
              <span className="status-dot teal" style={{ display: 'inline-block', marginRight: 6 }} />
              Ready / live
            </span>
            <span>
              <span className="status-dot violet" style={{ display: 'inline-block', marginRight: 6 }} />
              Fixture mode
            </span>
            <span>
              <span className="status-dot amber" style={{ display: 'inline-block', marginRight: 6 }} />
              Configured, unverified
            </span>
          </div>
        </div>
      </Card>

      <div className="grid-2" style={{ marginTop: 20 }}>
        <Card>
          <div className="card-head">
            <h2>
              <span className="head-icon violet">
                <ShieldCheck size={15} />
              </span>
              Connection readiness
            </h2>
            <span className="step-tag">MCP</span>
          </div>
          <div className="card-body">
            {!status ? (
              loading ? <div className="skeleton" aria-label="Loading connection readiness" style={{ height: 140 }} /> : <p className="small-empty">Connection readiness is unavailable. Apply an application key if required, then refresh.</p>
            ) : (
              <>
                <div className="status-grid">
                  {(
                    [
                      ['Mode', label(status.mode), status.mode === 'live' ? 'teal' : 'violet'],
                      ['Evidence source', status.provider_configured ? 'Configured' : 'Not set', status.provider_configured ? 'teal' : 'amber'],
                      ['Credentials', status.credentials_configured ? 'Configured' : 'Not set', status.credentials_configured ? 'teal' : 'amber'],
                      ['Live verified', status.live_verified ? 'Yes' : 'No', status.live_verified ? 'teal' : 'amber'],
                      ['History origin', label(status.local_history_origin), status.local_history_origin === 'published_synthetic_dataset' ? 'teal' : 'amber'],
                      ['Brief preparation', label(health?.agent_mode), health?.agent_mode === 'live' ? 'teal' : 'violet'],
                    ] as const
                  ).map(([k, v, tone]) => (
                    <div className="status-tile" key={k}>
                      <small>{k}</small>
                      <b>
                        <span className={`status-dot ${tone}`} />
                        {v}
                      </b>
                    </div>
                  ))}
                </div>
                <dl className="kv" style={{ marginTop: 14 }}>
                  <div>
                    <dt>MCP URL</dt>
                    <dd className="mono">{status.mcp_url || '—'}</dd>
                  </div>
                  <div>
                    <dt>Auth contract</dt>
                    <dd>{status.auth_contract}</dd>
                  </div>
                </dl>
              </>
            )}
          </div>
        </Card>

        <Card>
          <div className="card-head">
            <h2>
              <span className="head-icon amber">
                <KeyRound size={15} />
              </span>
              Application API key
            </h2>
            <Pill tone={keyApplied ? 'teal' : undefined} dot>
              {keyApplied ? 'Key applied' : 'No key'}
            </Pill>
          </div>
          <div className="card-body">
            <form onSubmit={applyKey}>
              <div className="field">
                <label htmlFor="api-key">
                  Key <span className="opt">/ only if CLAIMS_API_KEY is set on the server</span>
                </label>
                <input id="api-key" type="password" autoComplete="off" maxLength={300} value={key} onChange={(e) => setKey(e.target.value)} placeholder="Legacy application API key" />
                <small>Held in memory for this tab only. Cleared on reload or close.</small>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn primary" type="submit">
                  Apply key
                </button>
                <button className="btn ghost" type="button" onClick={clearKey}>
                  Clear key
                </button>
              </div>
            </form>
            <p className="footnote">Access credentials and provider configuration belong in the server environment. This browser never requests or stores passwords.</p>
          </div>
        </Card>
      </div>
    </motion.section>
  )
}
