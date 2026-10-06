import { Fragment } from 'react'
import { Check, Database, Gauge, ListChecks, Microscope, ShieldCheck, Tags, UserCheck } from 'lucide-react'
import { cx } from '../lib/format'

export const STAGES = [
  { key: 'classify', name: 'Classify', icon: Tags, blurb: 'Classifying the claim category' },
  { key: 'retrieve', name: 'Retrieve', icon: Database, blurb: 'Retrieving evidence and comparable historical cases' },
  { key: 'investigate', name: 'Investigate', icon: Microscope, blurb: 'Comparing evidence, gaps and contradictions' },
  { key: 'risk', name: 'Risk', icon: Gauge, blurb: 'Separating queue policy from statistical estimates' },
  { key: 'recommend', name: 'Recommend', icon: ListChecks, blurb: 'Preparing cited handler actions' },
  { key: 'validate', name: 'Validate', icon: ShieldCheck, blurb: 'Checking citations and decision boundaries' },
  { key: 'review', name: 'Review', icon: UserCheck, blurb: 'Waiting for a handler' },
] as const

export type NodeState = 'idle' | 'active' | 'done' | 'waiting' | 'warn'

/** Horizontal LangGraph pipeline. `states` maps stage key -> visual state. */
export function Pipeline({ states }: { states: Record<string, NodeState> }) {
  return (
    <div className="pipeline" role="list" aria-label="Investigation workflow stages">
      {STAGES.map((stage, index) => {
        const state = states[stage.key] ?? 'idle'
        const Icon = stage.icon
        const prevDone = index > 0 && ['done', 'warn', 'active', 'waiting'].includes(state)
        return (
          <Fragment key={stage.key}>
            {index > 0 && (
              <div className="pipe-link" aria-hidden="true">
                <div style={{ transform: `scaleX(${prevDone ? 1 : 0})` }} />
              </div>
            )}
            <div className={cx('pipe-node', state)} role="listitem" aria-label={`${stage.name}: ${state}`}>
              <div className="pipe-dot">
                {state === 'done' ? <Check size={17} strokeWidth={2.5} /> : <Icon size={17} />}
              </div>
              <span className="pipe-name">{stage.name}</span>
            </div>
          </Fragment>
        )
      })}
    </div>
  )
}

/** Static network mark, using the application's brand token. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="var(--teal)" strokeWidth="1.6" aria-hidden="true">
      <path d="M7 5h10M6 7l5 10m7-10-5 10" strokeLinecap="round" />
      {[[5, 5], [19, 5], [12, 19]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r="2.2" />)}
    </svg>
  )
}
