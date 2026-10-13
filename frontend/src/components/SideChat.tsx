import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { AlertTriangle, ClipboardCopy, Loader2, MessageSquareText, Send, X } from 'lucide-react'
import { api, post } from '../lib/api'
import type { Evidence, Run, SideAnswer, SideChatState, SidePart } from '../lib/api'
import { cx } from '../lib/format'
import { FeedbackBar } from './FeedbackBar'
import {
  answerAsText, askErrorMessage, citeLabel, confidenceTone, consultedLine, openableCites, questionProblem, sourceLabel, sourceNote, sourceTone,
} from '../lib/sideChat'

// A side conversation beside the investigation, like Claude's /btw: ask about this claim without changing it. Each answer
// says where it came from. The panel is not modal, so the brief stays readable and clickable behind it, and nothing asked
// here is added to the brief, its evidence or its checks.

const paragraphs = (text: string) => text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean)

/** Synapt's query agent writes markdown; show its **bold** as bold instead of asterisks. Everything stays React text, never HTML. */
const withBold = (text: string) =>
  text.split(/\*\*(.+?)\*\*/g).map((piece, i) => (i % 2 ? <strong key={i}>{piece}</strong> : piece))

function Cites({ ids, evidence, onOpen }: { ids: string[]; evidence: Evidence[]; onOpen: (id: string) => void }) {
  if (!ids.length) return null
  return (
    <span className="side-cites">
      {ids.map((id) => (
        <button key={id} type="button" className="side-cite" onClick={() => onOpen(id)} title={`Open as evidence: ${citeLabel(id, evidence)}`} aria-label={`Open evidence: ${citeLabel(id, evidence)}`}>
          {citeLabel(id, evidence)}
        </button>
      ))}
    </span>
  )
}

function SynaptExtras({ part, admin, evidence, onOpen }: { part: SidePart; admin: boolean; evidence: Evidence[]; onOpen: (id: string) => void }) {
  const s = part.synapt
  if (!s) return null
  const nums = s.confidence
  return (
    <div className="side-synapt">
      <div className="side-conf">
        <span className={cx('side-conf-label', confidenceTone(nums.label))} title={admin ? "Synapt's own scale: 70 and above is green (High), 40 to 70 orange (Medium), below 40 red (Low)" : 'Scale: 70 and above is High, 40 to 70 is Medium, below 40 is Low'}>Confidence: {nums.label}</span>
        {admin && typeof nums.overall === 'number' && (
          <span className="side-conf-nums">
            {nums.overall.toFixed(2)} overall
            {typeof nums.passages === 'number' && ` · knowledge store ${nums.passages.toFixed(2)}`}
            {typeof nums.procedures === 'number' && ` · procedure store ${nums.procedures.toFixed(2)}`}
            {typeof nums.graph === 'number' && ` · context graph ${nums.graph.toFixed(2)}`}
          </span>
        )}
      </div>
      {s.passages.length > 0 && (
        <div className="side-block">
          <span className="side-block-label">Passages it used</span>
          <ul className="side-list">
            {s.passages.map((c) => (
              <li key={c.chunk_id}>
                <span>{c.title}{c.source ? <span className="side-mono"> · {c.source}</span> : null}{admin && typeof c.score === 'number' ? <span className="side-mono"> · {c.score.toFixed(2)}</span> : null}</span>
                {c.in_evidence && <Cites ids={[c.chunk_id]} evidence={evidence} onOpen={onOpen} />}
              </li>
            ))}
          </ul>
        </div>
      )}
      {s.procedures.length > 0 && (
        <div className="side-block">
          <span className="side-block-label">Procedures it found</span>
          <ul className="side-chips">{s.procedures.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      {s.graph.nodes > 0 && (
        <div className="side-block">
          <span className="side-block-label">Knowledge graph it walked</span>
          <p className="side-graph">{s.graph.nodes} nodes and {s.graph.edges} connections{Object.keys(s.graph.by_label).length ? `: ${Object.entries(s.graph.by_label).map(([k, v]) => `${v} ${k.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase()}`).join(', ')}` : ''}.</p>
          {s.graph.top.length > 0 && <ul className="side-chips">{s.graph.top.map((n) => <li key={`${n.label}-${n.name}`}><span className="side-kind">{n.label}</span> {n.name}</li>)}</ul>}
        </div>
      )}
      {admin && (s.query_id || s.stores?.length) && (
        <details className="side-how">
          <summary>How it was answered</summary>
          <dl>
            {s.query_id && <><dt>Query ID (shown in Synapt’s Explainability)</dt><dd className="side-mono">{s.query_id}</dd></>}
            {s.stores?.length ? <><dt>Stores used</dt><dd>{s.stores.join(', ')}</dd></> : null}
            {typeof s.latency_ms === 'number' && <><dt>Retrieval time</dt><dd>{s.latency_ms} ms</dd></>}
          </dl>
        </details>
      )}
    </div>
  )
}

export function PartView({ part, admin, evidence, onOpen }: { part: SidePart; admin: boolean; evidence: Evidence[]; onOpen: (id: string) => void }) {
  const cites = openableCites(part, evidence)
  return (
    <section className={cx('side-part', sourceTone(part.source), part.status)} data-testid="side-part" data-source={part.source} data-status={part.status}>
      <header className="side-part-head">
        <span className="side-badge">{sourceLabel(part.source, admin)}</span>
        {part.status === 'declined' && <span className="side-state">Declined</span>}
        {part.status === 'unavailable' && <span className="side-state">Not available</span>}
      </header>
      {sourceNote(part.source, admin) && <p className="side-source-note">{sourceNote(part.source, admin)}</p>}
      {paragraphs(part.text).map((p, i) => <p key={i} className="side-text">{withBold(p)}</p>)}
      {part.facts.length > 0 && (
        <dl className="side-facts">
          {part.facts.map((f) => <div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}
        </dl>
      )}
      {part.items.length > 0 && (
        <ul className="side-items">
          {part.items.map((item, i) => (
            <li key={i}>
              {item.tag && <span className="side-tag">{item.tag}</span>}
              <span>{item.text}</span>
              <Cites ids={item.cites.filter((id) => evidence.some((e) => e.source_id === id))} evidence={evidence} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      )}
      {part.table && (
        <div className="side-table-wrap">
          <table className="side-table">
            <thead><tr>{part.table.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
            <tbody>{part.table.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j} data-label={part.table?.columns[j]}>{cell}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      <SynaptExtras part={part} admin={admin} evidence={evidence} onOpen={onOpen} />
      {part.notes.map((n) => <p key={n} className="side-note">{n}</p>)}
      {cites.length > 0 && part.source !== 'synapt' && (
        <div className="side-block"><span className="side-block-label">Evidence behind this</span><Cites ids={cites} evidence={evidence} onOpen={onOpen} /></div>
      )}
    </section>
  )
}

export function AnswerCard({ answer, admin, evidence, onOpen, onCopy, runId }: { answer: SideAnswer; admin: boolean; evidence: Evidence[]; onOpen: (id: string) => void; onCopy?: (text: string) => void; runId?: string }) {
  return (
    <article className="side-qa" data-testid="side-answer">
      <p className="side-question"><span className="side-q">You asked</span>{answer.question}</p>
      <div className="side-answer">
        {answer.repeat && <p className="side-repeat">You asked this before; this is the saved answer.</p>}
        {answer.parts.map((part, i) => <PartView key={`${part.source}-${i}`} part={part} admin={admin} evidence={evidence} onOpen={onOpen} />)}
        {runId && answer.id !== null && answer.parts.some((p) => p.source === 'synapt' && p.status === 'ok') && <FeedbackBar runId={runId} target={`side:${answer.id}`} admin={admin} />}
        <footer className="side-foot">
          <span>{consultedLine(answer, admin)}</span>
          {onCopy && <button type="button" className="side-copy" onClick={() => onCopy(answerAsText(answer, admin))} aria-label="Copy this answer as text"><ClipboardCopy size={13} aria-hidden="true" /> Copy</button>}
        </footer>
      </div>
    </article>
  )
}

type Phase = 'idle' | 'ready' | 'error'

export function SideChatPanel({ run, admin, open, onClose, onOpenSource, onCopy }: { run: Run; admin: boolean; open: boolean; onClose: () => void; onOpenSource: (id: string) => void; onCopy?: (text: string) => void }) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [items, setItems] = useState<SideAnswer[]>([])
  const [suggestions, setSuggestions] = useState<SideChatState['suggestions']>([])
  const [max, setMax] = useState(500)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<{ question: string; startedAt: number } | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [sendError, setSendError] = useState<string | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const requested = useRef(false)
  const evidence = run.evidence ?? []
  const base = `/api/investigations/${encodeURIComponent(run.run_id)}/side-chat`

  const load = useCallback(async () => {
    try {
      const data = await api<SideChatState>(base, { timeoutMs: 15_000 })
      setItems(data.items ?? [])
      setSuggestions(data.suggestions ?? [])
      setMax(data.limits?.max_question ?? 500)
      setLoadError(null)
      setPhase('ready')
    } catch (e) {
      setLoadError(askErrorMessage(e))
      setPhase('error')
    }
  }, [base])

  // The earlier questions and the suggestions are fetched the first time the panel opens.
  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement as HTMLElement | null
    if (!requested.current) { requested.current = true; void load() }
    const frame = requestAnimationFrame(() => input.current?.focus({ preventScroll: true }))
    return () => { cancelAnimationFrame(frame); opener.current?.focus?.({ preventScroll: true }) }
  }, [open, load])

  useEffect(() => {
    if (!pending) return
    const timer = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(timer)
  }, [pending])

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' }) }, [items.length, pending])

  const send = async (text: string) => {
    const question = text.trim()
    const problem = questionProblem(question, max)
    if (pending) return
    if (problem) { setSendError(problem); return }
    setSendError(null)
    setNow(Date.now())
    setPending({ question, startedAt: Date.now() })
    try {
      const answer = await post<SideAnswer>(base, { question }, { timeoutMs: 90_000 })
      // A repeated question returns the saved answer; show it once, at the end, instead of twice.
      setItems((list) => [...list.filter((i) => answer.id === null || i.id !== answer.id), answer])
      setDraft('')
    } catch (e) {
      setSendError(askErrorMessage(e))
    } finally {
      setPending(null)
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(draft) }
  }
  const remaining = max - draft.length
  const seconds = pending ? Math.max(0, Math.floor((now - pending.startedAt) / 1000)) : 0

  return (
    <aside id="side-panel" className="side-panel" role="dialog" aria-modal="false" aria-labelledby="side-title" hidden={!open} onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }}>
      <header className="side-head">
        <div>
          <h2 id="side-title"><MessageSquareText size={18} aria-hidden="true" /> Ask on the side</h2>
          <p className="side-sub">About this claim. <strong>Not part of the investigation:</strong> nothing here changes the brief, its evidence or its checks.</p>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close the side chat"><X size={16} /></button>
      </header>

      <div className="side-log" ref={log} role="log" aria-live="polite" aria-label="Side conversation">
        {phase === 'idle' && open && <p className="side-empty"><Loader2 size={14} className="spin" aria-hidden="true" /> Loading earlier questions…</p>}
        {phase === 'error' && (
          <div className="error" role="alert"><AlertTriangle size={16} /><span>{loadError} <button type="button" className="side-link" onClick={() => { setPhase('idle'); void load() }}>Try again</button></span></div>
        )}
        {phase === 'ready' && items.length === 0 && !pending && (
          <div className="side-intro">
            <p>Ask how to handle this claim, what a detail is, why the brief says something, how similar claims settled, or where the evidence came from. Each answer says which source it used.</p>
            <p className="side-intro-note">{admin ? 'Handling questions are answered by the Synapt knowledge base, which keeps a record of them. Everything else is read from this case, so no model is asked.' : 'Handling questions are answered by the knowledge base, which keeps a record of them. Everything else is read from this case, so no model is asked.'}</p>
          </div>
        )}
        {items.map((answer, i) => <AnswerCard key={`${answer.id ?? 'unsaved'}-${i}`} answer={answer} admin={admin} evidence={evidence} onOpen={onOpenSource} onCopy={onCopy} runId={run.run_id} />)}
        {pending && (
          <article className="side-qa" aria-busy="true">
            <p className="side-question"><span className="side-q">You asked</span>{pending.question}</p>
            <p className="side-pending"><Loader2 size={14} className="spin" aria-hidden="true" /> Checking this case and the knowledge base… {seconds}s</p>
          </article>
        )}
      </div>

      <footer className="side-compose">
        {phase === 'ready' && suggestions.length > 0 && (
          <div className="side-suggest" aria-label="Questions you could ask">
            {suggestions.map((s) => (
              <button key={s.text} type="button" className="side-suggestion" disabled={!!pending} onClick={() => { setDraft(s.text); setSendError(null); input.current?.focus() }}>{s.text}</button>
            ))}
          </div>
        )}
        {sendError && <p className="side-error" role="alert">{sendError}</p>}
        <div className="side-input-row">
          <textarea
            ref={input} value={draft} rows={2} maxLength={max + 50} disabled={!!pending}
            placeholder="Ask about this claim…" aria-label="Your question" onChange={(e) => { setDraft(e.target.value); if (sendError) setSendError(null) }} onKeyDown={onKey}
          />
          <button type="button" className="btn primary side-send" disabled={!!pending || !draft.trim()} onClick={() => void send(draft)} aria-label="Send the question"><Send size={15} aria-hidden="true" /></button>
        </div>
        <p className={cx('side-hint', remaining < 0 && 'over')}>Enter to send · Shift+Enter for a new line · Don’t type names or ID numbers; they are masked before anything is sent. <span className="side-count">{remaining}</span></p>
      </footer>
    </aside>
  )
}
