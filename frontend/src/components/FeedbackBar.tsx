import { useEffect, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { api, post } from '../lib/api'
import type { QueryFeedbackItem } from '../lib/api'
import { cx } from '../lib/format'
import { FEEDBACK_CHOICES, FEEDBACK_NOTE_MAX, feedbackErrorMessage, feedbackThanks } from '../lib/sideChat'

// "Was this answer useful?" under a knowledge-base answer. The handler's verdict is sent to Synapt (once per answer); the
// brief, its evidence and its checks are not touched. The query ID never reaches the page: the server looks it up.

export type FeedbackState = 'ready' | 'sending' | 'sent'

const cache = new Map<string, Promise<QueryFeedbackItem[]>>()
const load = (runId: string) => {
  if (!cache.has(runId)) {
    cache.set(runId, api<{ items: QueryFeedbackItem[] }>(`/api/investigations/${encodeURIComponent(runId)}/query-feedback`, { timeoutMs: 15_000 }).then((d) => d.items ?? []).catch((e) => { cache.delete(runId); throw e }))
  }
  return cache.get(runId) as Promise<QueryFeedbackItem[]>
}

/** The control itself, with its state as props so every state can be rendered and tested without a network. */
export function FeedbackView({ state, choice, error, note, onNote, onChoose, admin }: {
  state: FeedbackState; choice?: string | null; error?: string | null; note: string; onNote: (value: string) => void
  onChoose: (choice: string) => void; admin: boolean
}) {
  if (state === 'sent') {
    return (
      <p className="fb-sent" role="status" data-testid="feedback-sent">
        <Check size={14} aria-hidden="true" /> {feedbackThanks(choice ?? '', admin)}
      </p>
    )
  }
  return (
    <div className="fb" data-testid="feedback">
      <div className="fb-row">
        <span className="fb-label" id="fb-label">Was this answer useful?</span>
        <div className="fb-buttons" role="group" aria-labelledby="fb-label">
          {FEEDBACK_CHOICES.map((c) => (
            <button key={c.key} type="button" className={cx('fb-btn', choice === c.key && 'on')} disabled={state === 'sending'} onClick={() => onChoose(c.key)}>
              {state === 'sending' && choice === c.key ? <Loader2 size={13} className="spin" aria-hidden="true" /> : null}{c.label}
            </button>
          ))}
        </div>
      </div>
      <details className="fb-note">
        <summary>Add a note (optional)</summary>
        <textarea value={note} rows={2} maxLength={FEEDBACK_NOTE_MAX} aria-label="A note about this answer" onChange={(e) => onNote(e.target.value)} placeholder="What was missing or wrong?" />
        <p className="fb-hint">Personal details are masked before anything is sent. {FEEDBACK_NOTE_MAX - note.length} characters left.</p>
      </details>
      {error && <p className="fb-error" role="alert">{error}</p>}
      <p className="fb-hint">{admin ? 'Sent to Synapt as feedback on this query, once.' : 'Sent to the knowledge base as feedback on this answer, once.'} It does not change the brief.</p>
    </div>
  )
}

export function FeedbackBar({ runId, target, admin }: { runId: string; target: string; admin: boolean }) {
  const [state, setState] = useState<FeedbackState>('ready')
  const [loaded, setLoaded] = useState(false)
  const [choice, setChoice] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  // What has already been rated, so a verdict sent earlier (or in another tab) shows as sent.
  useEffect(() => {
    let live = true
    load(runId).then((items) => {
      if (!live) return
      const found = items.find((i) => i.target === target)
      if (found) { setChoice(found.choice); setState('sent') }
      setLoaded(true)
    }).catch(() => { if (live) setLoaded(true) })
    return () => { live = false }
  }, [runId, target])

  const send = async (picked: string) => {
    if (state === 'sending') return
    setChoice(picked)
    setError(null)
    setState('sending')
    try {
      await post(`/api/investigations/${encodeURIComponent(runId)}/query-feedback`, { target, choice: picked, ...(note.trim() ? { reason: note.trim() } : {}) }, { timeoutMs: 30_000 })
      cache.delete(runId)
      setState('sent')
    } catch (e) {
      const status = (e as { status?: number }).status
      if (status === 409) { cache.delete(runId); setState('sent'); return }
      setError(feedbackErrorMessage(e))
      setState('ready')
    }
  }

  if (!loaded) return null
  return <FeedbackView state={state} choice={choice} error={error} note={note} onNote={setNote} onChoose={(c) => void send(c)} admin={admin} />
}
