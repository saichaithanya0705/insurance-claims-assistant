import { MotionConfig, motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ArrowLeft,
  BrainCircuit,
  ClipboardCopy,
  Eye,
  FilePen,
  FilePlus2,
  FileText,
  FlaskConical,
  FolderOpen,
  Gauge,
  Bot,
  History,
  PanelRightOpen,
  Plug,
  RotateCcw,
  Search,
  UsersRound,
} from 'lucide-react'
import { api, post, type DemoCase, type EvaluationStatus, type Health, type ModelStatus, type Run } from './lib/api'
import { loadRecent, money, saveRecent, shortTitle, type RecentRun } from './lib/format'
import { Background, ErrorBox, Pill, ToastProvider, useToast } from './components/ui'
import { Sidebar, NAV, type View } from './components/Sidebar'
import { CommandPalette, type PaletteCommand } from './components/CommandPalette'
import { EMPTY_FILTERS, EMPTY_FORM, IntakeForm, buildClaim, buildFilters, formFromClaim, type FilterState, type FormState } from './components/IntakeForm'
import { LoadingState, RunView } from './components/Results'
import { BriefPreview } from './components/BriefPreview'
import { LiveActivity } from './components/LiveActivity'
import { newRunId } from './lib/liveProgress'
import { CaseLibrary } from './components/CaseLibrary'
import { Inspector } from './components/Inspector'
import { DataView } from './components/ui'
import { claimSnapshot } from './lib/presentation'
import { ReviewPanel } from './components/ReviewPanel'
import { QualityView } from './components/QualityView'
import { ConnectionView } from './components/ConnectionView'
import { CaseSearch } from './components/CaseSearch'
import { LoginGate, type User } from './components/LoginGate'
import { AccountsView } from './components/AccountsView'
import { ExplainabilityView } from './components/ExplainabilityView'
import { AgentsView } from './components/AgentsView'
import { ObservabilityView } from './components/ObservabilityView'

function Shell({ user, onLogout, authEnabled }: { user: User; onLogout: () => void; authEnabled: boolean }) {
  const admin = user.role === 'admin'
  const toast = useToast()
  const [view, setView] = useState<View>('workspace')
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [demoCases, setDemoCases] = useState<DemoCase[]>([])
  const [demoLoading, setDemoLoading] = useState(true)
  const [demoError, setDemoError] = useState<string | null>(null)
  const [intakeSession, setIntakeSession] = useState(0)
  const [resultFocus, setResultFocus] = useState(0)
  const resultsRef = useRef<HTMLDivElement>(null)
  const selectedRun = useRef<string | null>(null)
  const healthRequest = useRef(0)
  const demoRequest = useRef(0)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [selectedDemo, setSelectedDemo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [startedAt, setStartedAt] = useState(0)
  // The ID of the investigation being started now; the live panel follows it while the request is in flight.
  const [liveRunId, setLiveRunId] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [recent, setRecent] = useState<RecentRun[]>(() => loadRecent(user.id))
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)
  const [workspaceMode, setWorkspaceMode] = useState<'draft' | 'case'>('draft')
  const [explainRunId, setExplainRunId] = useState<string | null>(null)
  // `n` changes on every deep link so the view remounts and opens the requested trace even when
  // the same one was opened before.
  const [traceTarget, setTraceTarget] = useState<{ id: string; n: number } | null>(null)

  const loadHealth = useCallback(async () => {
    const request = ++healthRequest.current
    try {
      const result = await api<Health>('/api/health')
      if (request !== healthRequest.current) return
      setHealth(result)
      setHealthError(null)
    } catch (e) {
      if (request !== healthRequest.current) return
      setHealth(null)
      setHealthError((e as Error).message)
    }
  }, [])

  const loadDemos = useCallback(async () => {
    const request = ++demoRequest.current
    setDemoLoading(true)
    setDemoError(null)
    try {
      const cases = await api<DemoCase[]>('/api/demo-cases')
      if (request !== demoRequest.current) return
      setDemoCases(Array.isArray(cases) ? cases : [])
    } catch (e) {
      if (request !== demoRequest.current) return
      setDemoCases([])
      setDemoError((e as Error).message)
    } finally {
      if (request === demoRequest.current) setDemoLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHealth()
    loadDemos()
    return () => {
      healthRequest.current += 1
      demoRequest.current += 1
    }
  }, [loadHealth, loadDemos])

  const refreshApplication = useCallback(() => {
    void loadHealth()
    void loadDemos()
  }, [loadHealth, loadDemos])

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' })
    document.querySelector<HTMLElement>('.page h1')?.focus({ preventScroll: true })
  }, [view])

  useEffect(() => {
    if (!resultFocus || busy || view !== 'workspace') return
    resultsRef.current?.focus({ preventScroll: true })
    resultsRef.current?.scrollIntoView({ block: 'start', behavior: 'instant' })
    setResultFocus(0)
  }, [resultFocus, busy, view])

  const remember = useCallback((r: Run) => {
    setRecent((list) => {
      const entry: RecentRun = {
        run_id: r.run_id,
        title: `${shortTitle(r.claim?.description, 60) || 'Untitled incident'} · ${r.claim?.state ?? '—'}`,
        status: r.status,
        amount: r.claim?.claim_amount ?? 0,
        at: Date.now(),
      }
      const next = [entry, ...list.filter((x) => x.run_id !== r.run_id)].slice(0, 8)
      saveRecent(next, user.id)
      return next
    })
  }, [user.id])

  const showRun = useCallback(
    (r: Run) => {
      if (!r || typeof r !== 'object' || !r.run_id) throw new Error('The server response did not contain a valid investigation ID.')
      setRun(r)
      setWorkspaceMode('case')
      setDetailsOpen(false)
      setReviewOpen(false)
      setLookupError(null)
      selectedRun.current = r.run_id
      remember(r)
    },
    [remember],
  )

  const updateReviewedRun = useCallback((r: Run) => {
    if (!r?.run_id) throw new Error('The review response did not contain a valid investigation ID.')
    remember(r)
    if (selectedRun.current === r.run_id) setRun(r)
  }, [remember])

  // The independent judge, and sometimes the query agent's answer, finish in the background; pick them up without a reload.
  const pendingRun = run?.judge?.status === 'pending' || run?.query_agent?.pending ? run.run_id : null
  useEffect(() => {
    if (!pendingRun) return
    let attempts = 0
    const timer = window.setInterval(async () => {
      attempts += 1
      try {
        const latest = await api<Run>(`/api/investigations/${encodeURIComponent(pendingRun)}`)
        const judged = !latest.judge || latest.judge.status !== 'pending'
        const answered = !latest.query_agent?.pending
        setRun((current) => (current?.run_id === pendingRun ? { ...current, judge: latest.judge ?? current.judge, query_agent: latest.query_agent ?? current.query_agent } : current))
        if (judged && answered) window.clearInterval(timer)
      } catch {
        /* transient: keep trying until the attempts run out */
      }
      if (attempts >= 36) window.clearInterval(timer) // about three minutes at five seconds
    }, 5000)
    return () => window.clearInterval(timer)
  }, [pendingRun])

  const loadDemo = (index: number) => {
    const demo = demoCases[index]
    if (!demo?.claim) return
    setResultFocus(0)
    setWorkspaceMode('draft')
    setForm(formFromClaim(demo.claim))
    setIntakeSession((n) => n + 1)
    setSelectedDemo(demo.id)
    setFormError(null)
    setView('workspace')
    toast(`Loaded "${demo.title}". Review the details before running.`, 'info')
  }

  const investigate = async (submittedForm: FormState) => {
    if (busy) return
    setFormError(null)
    let body
    try {
      body = { claim: buildClaim(submittedForm), filters: buildFilters(filters) }
    } catch (e) {
      setFormError((e as Error).message)
      return
    }
    const runId = newRunId()
    setStartedAt(Date.now())
    setLiveRunId(runId)
    setBusy(true)
    selectedRun.current = null
    try {
      const result = await post<Run>('/api/investigations', { ...body, run_id: runId })
      showRun(result)
      setForm(EMPTY_FORM)
      setFilters(EMPTY_FILTERS)
      setSelectedDemo(null)
      void loadHealth()
      setResultFocus((n) => n + 1)
      toast(result.status === 'failed' ? 'Investigation failed safely. See the brief for details.' : 'Investigation brief ready for review.', result.status === 'failed' ? 'err' : 'ok')
    } catch (e) {
      selectedRun.current = run?.run_id ?? null
      setFormError((e as Error).message)
    } finally {
      setLiveRunId(null)
      setBusy(false)
    }
  }

  const openRun = useCallback(
    async (id: string) => {
      const runId = id.trim()
      if (!runId || busy) return
      setView('workspace')
      setLookupError(null)
      setStartedAt(Date.now())
      setBusy(true)
      selectedRun.current = runId
      setFormError(null)
      try {
        showRun(await api<Run>(`/api/investigations/${encodeURIComponent(runId)}`))
        setResultFocus((n) => n + 1)
      } catch (e) {
        selectedRun.current = run?.run_id ?? null
        setLookupError((e as Error).message)
        requestAnimationFrame(() => document.getElementById('claim-search')?.focus())
      } finally {
        setBusy(false)
      }
    },
    [busy, showRun, run?.run_id],
  )

  const openExplain = useCallback((runId: string) => {
    setExplainRunId(runId)
    setView('explain')
  }, [])

  const openTrace = useCallback((runId: string) => {
    setTraceTarget((current) => ({ id: runId, n: (current?.n ?? 0) + 1 }))
    setView('observability')
  }, [])

  const navigate = useCallback((next: View) => {
    if (next === 'observability') setTraceTarget(null)
    setView(next)
  }, [])

  const resetForm = () => {
    setWorkspaceMode('draft')
    setView('workspace')
    setResultFocus(0)
    setIntakeSession((n) => n + 1)
    setForm(EMPTY_FORM)
    setFilters(EMPTY_FILTERS)
    setSelectedDemo(null)
    setFormError(null)
  }

  /* ---------- Keyboard shortcuts ---------- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
      } else if (e.altKey && ['1', '2', '3', '4', '5', '6', '7', '8'].includes(e.key)) {
        e.preventDefault()
        const item = NAV.find(n => n.key === e.key)
        if (item && (admin || !item.admin)) navigate(item.view)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [admin, navigate])

  /* ---------- Command palette ---------- */
  const commands = useMemo<PaletteCommand[]>(() => {
    const list: PaletteCommand[] = [
      { id: 'v-ws', group: 'Navigate', label: 'Investigation workspace', hint: 'Alt 1', icon: <FilePlus2 size={15} />, run: () => setView('workspace') },
      { id: 'v-cases', group: 'Navigate', label: 'Open saved cases', hint: 'Alt 2', icon: <FolderOpen size={15} />, run: () => setView('cases') },
      { id: 'v-xp', group: 'Navigate', label: 'Explainability', hint: 'Alt 3', icon: <Eye size={15} />, run: () => setView('explain') },
      { id: 'v-agents', group: 'Navigate', label: 'Agents and their tools', hint: 'Alt 4', icon: <Bot size={15} />, run: () => setView('agents') },
      { id: 'v-obs', group: 'Navigate', label: 'Observability and traces', hint: 'Alt 5', icon: <Activity size={15} />, run: () => navigate('observability') },
      { id: 'v-q', group: 'Navigate', label: 'Quality & models', hint: 'Alt 6', icon: <Gauge size={15} />, run: () => setView('quality') },
      { id: 'v-c', group: 'Navigate', label: 'Connection settings', hint: 'Alt 7', icon: <Plug size={15} />, run: () => setView('connection') },
      { id: 'v-accounts', group: 'Navigate', label: 'Manage accounts', hint: 'Alt 8', icon: <UsersRound size={15} />, run: () => setView('accounts') },
      ...demoCases.map((d, i) => ({
        id: `demo-${d.id}`,
        group: 'Load demo case',
        label: d.title,
        hint: `${d.claim.state} · ${money(d.claim.claim_amount)}`,
        icon: <FileText size={15} />,
        run: () => loadDemo(i),
      })),
      ...recent.map((r) => ({
        id: `recent-${r.run_id}`,
        group: 'Open recent run',
        label: r.title,
        hint: r.run_id.slice(0, 8),
        icon: <History size={15} />,
        run: () => openRun(r.run_id),
      })),
      {
        id: 'a-train',
        group: 'Actions',
        label: 'Train statistical models',
        icon: <BrainCircuit size={15} />,
        run: async () => {
          toast('Training models…', 'info')
          try {
            const r = await post<ModelStatus>('/api/models/train')
            toast(r.available ? 'Model training completed.' : r.reason || 'Training returned no models.', r.available ? 'ok' : 'info')
          } catch (e) {
            toast((e as Error).message, 'err')
          }
        },
      },
      {
        id: 'a-eval',
        group: 'Actions',
        label: 'Run golden-case evaluations',
        icon: <FlaskConical size={15} />,
        run: async () => {
          toast('Running evaluations…', 'info')
          try {
            const r = await post<EvaluationStatus>('/api/evaluations/run', { judge: false })
            toast(`Evaluations: ${r.passed ?? 0}/${r.total ?? 0} cases passed.`, r.passed === r.total ? 'ok' : 'info')
          } catch (e) {
            toast((e as Error).message, 'err')
          }
        },
      },
      { id: 'a-reset', group: 'Actions', label: 'Clear intake form', icon: <RotateCcw size={15} />, run: () => (resetForm(), setView('workspace')) },
      {
        id: 'a-explain',
        group: 'Actions',
        label: 'Explain the current run',
        icon: <Eye size={15} />,
        disabled: !run,
        run: () => run && openExplain(run.run_id),
      },
      {
        id: 'a-trace',
        group: 'Actions',
        label: 'Open the trace of the current run',
        icon: <Activity size={15} />,
        disabled: !run,
        run: () => run && openTrace(run.run_id),
      },
      {
        id: 'a-copy',
        group: 'Actions',
        label: 'Copy current run ID',
        icon: <ClipboardCopy size={15} />,
        disabled: !run,
        run: () => run && navigator.clipboard.writeText(run.run_id).then(() => toast('Run ID copied.')),
      },
    ]
    return admin ? list : list.filter(command => !['v-obs', 'v-q', 'v-c', 'v-accounts', 'a-train', 'a-eval', 'a-trace'].includes(command.id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoCases, recent, run, openRun, openExplain, openTrace, navigate, toast, admin])

  const crumb = NAV.find((n) => n.view === view)?.label

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Background />
      <div className="shell">
        <Sidebar view={view} onView={navigate} recent={recent} onOpenRecent={openRun} onPalette={() => setPaletteOpen(true)} admin={admin} />
        <main className="main" id="main-content">
          <header className="topbar">
            <div className="crumbs">
              Claims workspace <span>/</span> <b>{crumb}</b>
            </div>
            <div className="status-cluster" aria-live="polite">
              {healthError ? (
                <Pill tone="rose" dot>
                  Application unavailable
                </Pill>
              ) : !health ? (
                <Pill>Checking…</Pill>
              ) : (
                <>
                  <Pill tone={health.status === 'ok' ? 'teal' : 'amber'} dot>
                    {health.status === 'ok' ? 'All systems normal' : 'Service degraded'}
                  </Pill>
                </>
              )}
              <button className="icon-btn" onClick={() => setPaletteOpen(true)} aria-label="Open command palette (Ctrl K)" title="Command palette (Ctrl K)">
                <Search size={15} />
              </button>
              <span className="signed-in"><span className="avatar" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</span><span className="who"><b>{user.username}</b><small>{admin ? 'Administrator' : 'Handler'}</small></span></span>
              {authEnabled && <button className="btn" disabled={busy} onClick={onLogout}>Sign out</button>}
            </div>
          </header>

          <div className="page">
            <div>
              {view === 'workspace' && (
                <motion.section key="workspace" aria-label="Investigation workspace" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.3 }}>
                  <div className="page-head">
                    <div>
                      <div className="eyebrow">Claims investigator</div>
                      <h1 className="display" tabIndex={-1}>
                        Claims investigation
                      </h1>
                      {workspaceMode === 'draft' && <p className="subtitle">Compare evidence, resolve gaps and prepare the brief for handler review.</p>}
                    </div>
                    <div className="case-search-wrap"><CaseSearch onOpen={openRun} disabled={busy} onQueryChange={() => setLookupError(null)} /><ErrorBox message={lookupError} /></div>
                  </div>

                  {healthError ? (
                    <div style={{ marginBottom: 22 }}>
                      <ErrorBox message={`The application could not be reached (${healthError}). Check that uvicorn is running, then refresh.`} />
                    </div>
                  ) : null}

                  <div className="case-toolbar">
                    <div className="case-toolbar-nav">
                      <button className="btn ghost" onClick={() => setView('cases')}><ArrowLeft size={15} /> Saved cases</button>
                      {run && workspaceMode === 'draft' && <button className="btn ghost" onClick={() => setWorkspaceMode('case')}>Return to case</button>}
                      {workspaceMode === 'case' && form.description && <button className="btn ghost" disabled={busy} onClick={() => setWorkspaceMode('draft')}>Resume draft</button>}
                      {workspaceMode === 'case' && <button className="btn ghost" disabled={busy} onClick={resetForm}><FilePlus2 size={15} /> New investigation</button>}
                    </div>
                    {run && workspaceMode === 'case' && <div className="case-toolbar-actions">
                      <button className="btn ghost" onClick={() => setDetailsOpen(true)}><PanelRightOpen size={15} /> Saved input</button>
                      <button className="btn" disabled={busy} onClick={() => { setForm(formFromClaim(run.claim)); setFilters(EMPTY_FILTERS); setSelectedDemo(null); setFormError(null); setIntakeSession(n => n + 1); setWorkspaceMode('draft') }}><FilePen size={15} /> Revise</button>
                    </div>}
                  </div>
                  {busy && workspaceMode === 'case' && run && <p role="status">Opening saved investigation… The current case stays visible until loading succeeds.</p>}
                  <div className={`workspace ${workspaceMode === 'draft' && !busy ? 'composer' : 'reading'}`}>
                    {workspaceMode === 'draft' && !busy && <IntakeForm
                      key={intakeSession}
                      form={form}
                      setForm={(f) => {
                        setForm(f)
                        if (selectedDemo) setSelectedDemo(null)
                      }}
                      filters={filters}
                      setFilters={setFilters}
                      demoCases={demoCases}
                      demoLoading={demoLoading}
                      demoError={demoError}
                      onRetryDemos={loadDemos}
                      selectedDemo={selectedDemo}
                      onDemo={loadDemo}
                      busy={busy}
                      error={formError}
                      onSubmit={investigate}
                      onReset={resetForm}
                    />}
                    {(busy || workspaceMode === 'case') && <div className="output results-anchor" ref={resultsRef} tabIndex={-1} aria-label="Investigation output">
                      <div>
                        {busy && (workspaceMode === 'draft' || !run) ? (
                          <motion.div key="loading" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}>
                            {liveRunId ? <><LiveActivity key={liveRunId} runId={liveRunId} startedAt={startedAt} admin={admin} /><BriefPreview key={`preview-${liveRunId}`} runId={liveRunId} admin={admin} /></> : <LoadingState startedAt={startedAt} />}
                          </motion.div>
                        ) : run ? (
                          <motion.div key={run.run_id} className="output" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                            <RunView key={run.run_id} run={run} onDetails={() => setDetailsOpen(true)} onReview={() => { if (!busy) setReviewOpen(true) }} admin={admin} onExplain={() => openExplain(run.run_id)} onTrace={admin ? () => openTrace(run.run_id) : undefined} />
                          </motion.div>
                        ) : null                        }
                      </div>
                    </div>}
                  </div>
                  {detailsOpen && run && <Inspector title="Saved input snapshot · This investigation" onClose={() => setDetailsOpen(false)}><p className="section-desc">These are the saved inputs for ID {run.run_id}. Draft edits never alter this snapshot.</p><DataView value={claimSnapshot(run.claim)} /><h3>Documents reported available</h3><p>{run.claim.provided_documents?.join(', ') || 'None reported'}. Names only; no content attached, extracted or reviewed.</p></Inspector>}
                  {admin && reviewOpen && run && <Inspector title="Review this brief" onClose={() => setReviewOpen(false)}><ReviewPanel run={run} onUpdated={updateReviewedRun} /></Inspector>}
                </motion.section>
              )}
              {view === 'cases' && <motion.section key="cases" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}><div className="page-head"><div><div className="eyebrow">Case queue</div><h1 className="display" tabIndex={-1}>Saved cases</h1><p className="subtitle">Open a brief, or sort by priority to work the queue.</p></div><button className="btn primary" disabled={busy} onClick={resetForm}><FilePlus2 size={15} /> New investigation</button></div><CaseLibrary onOpen={openRun} busy={busy} /></motion.section>}
              {view === 'agents' && <AgentsView admin={admin} />}
              {view === 'explain' && <ExplainabilityView admin={admin} runId={explainRunId} onSelect={setExplainRunId} onOpenTrace={openTrace} />}
              {admin && view === 'observability' && <ObservabilityView key={traceTarget?.n ?? 0} focusRun={traceTarget?.id ?? null} onExplain={openExplain} />}
              {admin && view === 'accounts' && <AccountsView />}
              {admin && view === 'quality' && (
                <motion.div key="quality" exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
                  <QualityView />
                </motion.div>
              )}
              {admin && view === 'connection' && (
                <motion.div key="connection" exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}>
                  <ConnectionView health={health} onHealthRefresh={refreshApplication} />
                </motion.div>
              )}
            </div>
          </div>
          <footer className="footer">
            <span>Claims Investigator · Educational claims decision support</span>
            <span>
              Evidence informs. A person decides.
            </span>
          </footer>
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
    </>
  )
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <LoginGate component={Shell} />
      </ToastProvider>
    </MotionConfig>
  )
}
