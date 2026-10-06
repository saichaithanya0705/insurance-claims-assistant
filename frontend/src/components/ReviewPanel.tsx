import { motion } from 'motion/react'
import { useState, type FormEvent } from 'react'
import { AlertTriangle, CheckCircle2, MessageSquareText, RotateCcw, Star, UserCheck } from 'lucide-react'
import { api, post, type Run } from '../lib/api'
import { cx, label } from '../lib/format'
import { Card, ErrorBox, Pill, useToast } from './ui'
import { statusTone } from './Results'

export function ReviewPanel({ run, onUpdated }: { run: Run; onUpdated: (run: Run) => void }) {
  const toast = useToast()
  const [note, setNote] = useState('')
  const [rating, setRating] = useState(0)
  const [feedbackNote, setFeedbackNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<null | 'review' | 'feedback'>(null)
  const [feedbackSaved, setFeedbackSaved] = useState<string | null>(null)

  const waiting = ['awaiting_review', 'needs_manual_review'].includes(run.status)
  const validationPassed = run.validation?.passed === true
  const decision = run.review?.decision

  const submitReview = async (choice: 'accept_brief' | 'request_revision') => {
    setError(null)
    if (note.trim().length < 3) {
      setError('Add a review note of at least three characters.')
      document.getElementById('review-note')?.focus()
      return
    }
    setSaving('review')
    try {
      let result = await post<Run>(`/api/investigations/${encodeURIComponent(run.run_id)}/review`, { decision: choice, note: note.trim() })
      if (!result?.run_id) result = await api<Run>(`/api/investigations/${encodeURIComponent(run.run_id)}`)
      onUpdated(result)
      toast(choice === 'accept_brief' ? 'Brief accepted for your review record.' : 'Revision requested.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(null)
    }
  }

  const submitFeedback = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!rating) {
      setError('Choose a usefulness rating from 1 to 5.')
      document.getElementById(`rating-${run.run_id}-1`)?.focus()
      return
    }
    if (feedbackNote.trim().length < 3) {
      setError('Add a feedback note of at least three characters.')
      document.getElementById('feedback-note')?.focus()
      return
    }
    setSaving('feedback')
    try {
      const result = await post<{ reviewed: boolean }>(`/api/investigations/${encodeURIComponent(run.run_id)}/feedback`, { rating, note: feedbackNote.trim() })
      setFeedbackSaved(result.reviewed ? 'Saved. Reviewed-run feedback becomes a lesson candidate.' : 'Saved. Feedback on unreviewed runs is not promoted to lesson candidates.')
      setFeedbackNote('')
      toast('Feedback saved.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card aria-labelledby="review-title">
      <div className="card-head">
        <h2 id="review-title">
          <span className="head-icon violet">
            <UserCheck size={15} />
          </span>
          Handler review
        </h2>
        <Pill tone={decision === 'accept_brief' ? 'teal' : statusTone(run.status)} dot>
          {decision ? label(decision) : run.status === 'failed' ? 'Run failed' : run.status === 'needs_manual_review' ? 'Manual review required' : 'Awaiting review'}
        </Pill>
      </div>
      <div className="review-grid">
        <div>
          <p style={{ fontSize: 12.5, color: 'var(--text-2)', marginBottom: 14 }}>
            Accept this brief for your review record, or request a revision. This does <b>not</b> approve or deny the claim.
          </p>
          {decision && (
            <motion.div className="review-log" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
              <CheckCircle2 size={16} />
              <span>
                <b>{label(decision)}:</b> {run.review?.note || 'No note returned'}
              </span>
            </motion.div>
          )}
          {waiting && !validationPassed && (
            <div className="review-log warn">
              <AlertTriangle size={16} />
              <span>Validation did not pass. Acceptance is blocked; record a revision request or investigate manually.</span>
            </div>
          )}
          <div className="field">
            <label htmlFor="review-note">
              Review note <span className="counter">{note.length}/2000</span>
            </label>
            <textarea id="review-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} placeholder="Record your assessment or what needs to change." disabled={!waiting || saving !== null} style={{ minHeight: 84 }} />
          </div>
          <div className="review-actions">
            <button className="btn primary" type="button" disabled={!waiting || !validationPassed || saving !== null} onClick={() => submitReview('accept_brief')}>
              <CheckCircle2 size={15} /> Accept brief
            </button>
            <button className="btn" type="button" disabled={!waiting || saving !== null} onClick={() => submitReview('request_revision')}>
              <RotateCcw size={15} /> Request revision
            </button>
          </div>
        </div>
        <form onSubmit={submitFeedback}>
          <div className="form-section-title">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <MessageSquareText size={13} /> Usefulness feedback
            </span>
          </div>
          <fieldset className="stars" disabled={saving !== null} style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field-label" style={{ marginBottom: 8 }}>Usefulness rating</legend>
            {[1, 2, 3, 4, 5].map((n) => (
              <label
                key={n}
                className={cx('star', rating >= n && 'on')}
              >
                <input id={`rating-${run.run_id}-${n}`} type="radio" name={`usefulness-${run.run_id}`} value={n} checked={rating === n} onChange={() => setRating(n)} aria-label={`${n} of 5`} required />
                <Star size={24} fill={rating >= n ? 'currentColor' : 'none'} aria-hidden="true" />
              </label>
            ))}
          </fieldset>
          <div className="field" style={{ marginTop: 12 }}>
            <label htmlFor="feedback-note">Feedback note</label>
            <input id="feedback-note" value={feedbackNote} onChange={(e) => setFeedbackNote(e.target.value)} minLength={3} maxLength={2000} required disabled={saving !== null} placeholder="What was useful or missing?" />
          </div>
          <button className="btn" type="submit" disabled={saving !== null}>
            Save feedback
          </button>
          {feedbackSaved && (
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="footnote" style={{ marginTop: 10 }}>
              {feedbackSaved}
            </motion.p>
          )}
        </form>
      </div>
      {error && (
        <div style={{ padding: '0 22px 22px' }}>
          <ErrorBox message={error} />
        </div>
      )}
    </Card>
  )
}
