import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, ChevronRight, Hourglass, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import type { AgentInfo, LiveProgress } from '../lib/api'
import { cx } from '../lib/format'
import { activeStage, buildGroups, elapsedMs, emptyView, followProgress, isLive, stageStates, stateLine } from '../lib/liveProgress'
import type { LiveGroup, LiveRow, LiveView } from '../lib/liveProgress'
import { formatDuration } from '../lib/trace'
import { Card } from './ui'
import { Pipeline } from './Pipeline'
import { AgentTeamView, useAgentRoster } from './AgentTeam'

// What an investigation is doing right now, shown while the request is in flight. Every line is a span the server
// really opened (the server sends nothing else), with the time it really took; a call that has not returned yet counts
// up. The server decides how much detail a viewer may see: an administrator also gets the tool, the query and the model.

/** Follow one run's progress until it ends or the component goes away. */
function useLiveProgress(runId: string): LiveView {
  const [view, setView] = useState<LiveView>(emptyView)
  useEffect(() => {
    const follower = followProgress({
      load: (after, signal) =>
        api<LiveProgress>(`/api/investigations/${encodeURIComponent(runId)}/progress?after=${after}`, { signal, timeoutMs: 8000 }),
      onUpdate: setView,
    })
    return () => follower.stop()
  }, [runId])
  return view
}

/** A browser clock that ticks only while something is still running, so a finished page stays still. `now` is the
 *  monotonic clock used to carry a running span forward; `wall` is the time of day, for the total elapsed. */
function useClock(active: boolean): { now: number; wall: number } {
  const [clock, setClock] = useState(() => ({ now: performance.now(), wall: Date.now() }))
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setClock({ now: performance.now(), wall: Date.now() }), 250)
    return () => window.clearInterval(timer)
  }, [active])
  return clock
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'running') return <Loader2 size={15} className="spin" aria-label="Running" />
  if (status === 'ok') return <Check size={15} aria-label="Done" />
  if (status === 'error') return <AlertTriangle size={15} aria-label="Failed" />
  return <Hourglass size={15} aria-label="Waiting" />
}

function Row({ row, view, now, bounds }: { row: LiveRow; view: LiveView; now: number; bounds: { start: number; length: number } }) {
  const { span } = row
  const ms = elapsedMs(span, view, now)
  const left = bounds.length > 0 ? Math.min(98, Math.max(0, ((span.started_ms - bounds.start) / bounds.length) * 100)) : 0
  const width = bounds.length > 0 ? Math.min(100 - left, Math.max(1.5, (ms / bounds.length) * 100)) : 100
  return (
    <li className={cx('live-row', span.status, span.background && 'background')} style={{ paddingLeft: `${row.depth * 16}px` }} data-testid="live-row" data-status={span.status}>
      <span className="live-ico"><StatusIcon status={span.status} /></span>
      <div className="live-body">
        <div className="live-line">
          <span className="live-label">{span.label}</span>
          {span.result && <span className="live-result">{span.result}</span>}
          {span.background && <span className="live-bg">in the background</span>}
          <span className="live-time">{formatDuration(ms)}</span>
        </div>
        {span.detail && <div className="live-detail">{span.detail}</div>}
        <div className="live-bar" aria-hidden="true"><i style={{ left: `${left}%`, width: `${width}%` }} /></div>
      </div>
    </li>
  )
}

function Group({ group, view, now, open, onToggle }: { group: LiveGroup; view: LiveView; now: number; open: boolean; onToggle: () => void }) {
  const stage = group.stage
  const status = stage?.status ?? 'ok'
  const elapsed = stage ? elapsedMs(stage, view, now) : 0
  const start = stage?.started_ms ?? Math.min(...group.rows.map((r) => r.span.started_ms))
  const end = Math.max(
    stage ? stage.started_ms + elapsed : start,
    ...group.rows.map((r) => r.span.started_ms + elapsedMs(r.span, view, now)),
  )
  const calls = group.rows.filter((r) => r.span.kind !== 'stage').length
  return (
    <section className={cx('live-group', status)} data-testid="live-group">
      <button type="button" className="live-group-head" aria-expanded={open} onClick={onToggle}>
        <ChevronRight size={15} className="live-chev" aria-hidden="true" />
        <span className="live-ico"><StatusIcon status={status} /></span>
        <span className="live-group-title">{stage ? stage.label : 'Other steps'}</span>
        {stage?.result && <span className="live-result">{stage.result}</span>}
        <span className="live-group-meta">{calls} {calls === 1 ? 'step' : 'steps'}{stage ? ` · ${formatDuration(elapsed)}` : ''}</span>
      </button>
      {open && (
        <ol className="live-rows" aria-label={`Steps in: ${stage ? stage.label : 'other steps'}`}>
          {group.rows.map((row) => (
            <Row key={row.span.id} row={row} view={view} now={now} bounds={{ start, length: Math.max(1, end - start) }} />
          ))}
          {group.rows.length === 0 && <li className="live-empty">No separate steps recorded for this stage.</li>}
        </ol>
      )}
    </section>
  )
}

/** The page for one view of a run. Pure: the view and the two clocks come in as props, so it renders the same way in a test. */
export function LiveActivityView({ view, now, wall, startedAt, admin, roster = null }: { view: LiveView; now: number; wall: number; startedAt: number; admin: boolean; roster?: readonly AgentInfo[] | null }) {
  const live = isLive(view)
  const groups = useMemo(() => buildGroups(view), [view])
  const states = useMemo(() => stageStates(view), [view])
  const active = activeStage(view)
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const seconds = Math.max(0, Math.floor((wall - startedAt) / 1000))
  const activeGroup = groups.find((g) => g.key === active)
  const announcement = activeGroup?.stage ? `${activeGroup.stage.label}: running` : view.state === 'queued' ? 'Waiting for another investigation to finish' : ''
  const hasSteps = groups.length > 0
  return (
    <Card className="live-card" aria-busy={live} data-testid="live-activity">
      <div className="live-head">
        <div>
          <h2>Building the investigation</h2>
          <p className="live-state" role="status">{stateLine(view, admin)}</p>
        </div>
        <div className="live-clock" aria-label={`Elapsed ${seconds} seconds`}>
          {live && <Loader2 size={16} className="spin" aria-hidden="true" />}
          <span>{seconds}s</span>
        </div>
      </div>
      <Pipeline states={states} />
      {roster && roster.length > 0 && <AgentTeamView view={view} roster={roster} now={now} />}
      {hasSteps && (
        <p className="live-counts">
          {view.counts.knowledge_calls} knowledge-store {view.counts.knowledge_calls === 1 ? 'call' : 'calls'} · {view.counts.model_calls} model {view.counts.model_calls === 1 ? 'call' : 'calls'}
          {view.counts.open > 0 && <> · {view.counts.open} in progress now</>}
        </p>
      )}
      {hasSteps ? (
        <div className="live-feed">
          {groups.map((group) => {
            const status = group.stage?.status
            const open = toggled[group.key] ?? (status === 'running' || status === 'error' || status === 'waiting')
            return <Group key={group.stage?.id ?? group.key} group={group} view={view} now={now} open={open} onToggle={() => setToggled((t) => ({ ...t, [group.key]: !open }))} />
          })}
        </div>
      ) : view.state === 'unavailable' ? (
        <p className="live-note">Live steps are not available for this run. It is still being built, and the brief appears when it is done.</p>
      ) : null}
      {view.truncated && <p className="live-note">This run made more steps than are listed here; the saved trace has all of them.</p>}
      <p className="live-note">
        Every line is a call this investigation really made, shown as it happens; nothing here is simulated. You can visit other
        views and come back while it runs; keep this browser tab open, because refreshing cannot resume an in-flight request.
      </p>
      <div className="sr-only" aria-live="polite">{announcement}</div>
    </Card>
  )
}

/** Follows `runId` while the request is in flight and shows what the investigation is doing. */
export function LiveActivity({ runId, startedAt, admin }: { runId: string; startedAt: number; admin: boolean }) {
  const view = useLiveProgress(runId)
  const { now, wall } = useClock(isLive(view))
  const roster = useAgentRoster()
  return <LiveActivityView view={view} now={now} wall={wall} startedAt={startedAt} admin={admin} roster={roster} />
}
