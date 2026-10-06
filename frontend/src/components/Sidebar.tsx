import { motion } from 'motion/react'
import { Command, LayoutGrid, Network, ShieldCheck } from 'lucide-react'
import { BrandMark } from './Pipeline'
import { cx, money, timeAgo, type RecentRun } from '../lib/format'

export type View = 'workspace' | 'cases' | 'quality' | 'connection' | 'accounts'

export const NAV: { view: View; label: string; icon: typeof LayoutGrid; key: string; admin?: boolean }[] = [
  { view: 'workspace', label: 'Investigation', icon: LayoutGrid, key: '1' },
  { view: 'quality', label: 'Quality & models', icon: ShieldCheck, key: '2', admin: true },
  { view: 'cases', label: 'Saved cases', icon: LayoutGrid, key: '4' },
  { view: 'connection', label: 'Connection', icon: Network, key: '3', admin: true },
  { view: 'accounts', label: 'Accounts', icon: ShieldCheck, key: '', admin: true },
]

const dotTone = (status: string) =>
  status === 'reviewed' ? 'teal' : status === 'failed' ? 'rose' : status === 'revision_requested' ? 'violet' : 'amber'

export function Sidebar({
  view,
  onView,
  recent,
  onOpenRecent,
  onPalette,
  admin,
}: {
  view: View
  onView: (v: View) => void
  recent: RecentRun[]
  onOpenRecent: (id: string) => void
  onPalette: () => void
  admin: boolean
}) {
  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="brand">
        <div className="brand-mark">
          <BrandMark />
        </div>
        <div className="brand-text">
          <div className="brand-name">Claims</div>
          <div className="brand-sub">Investigator</div>
        </div>
      </div>

      <nav className="nav">
        <div className="nav-label">Workspace</div>
        {NAV.filter(item => admin || !item.admin).map((item) => {
          const active = item.view === view
          const Icon = item.icon
          return (
            <button
              key={item.view}
              className={cx('nav-item', active && 'active')}
              onClick={() => onView(item.view)}
              aria-current={active ? 'page' : undefined}
              aria-label={item.label}
              title={item.label}
            >
              {active && (
                <>
                  <motion.span layoutId="nav-bg" className="nav-bg" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
                  <motion.span layoutId="nav-bar" className="nav-bar" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
                </>
              )}
              <Icon size={18} />
              <span className="lbl">{item.label}</span>
              {item.key && <span className="kbd">Alt {item.key}</span>}
            </button>
          )
        })}
      </nav>

      {recent.length > 0 && (
        <div className="recent">
          <div className="nav-label">Recent runs</div>
          {recent.slice(0, 5).map((run) => (
            <button key={run.run_id} className="recent-item" onClick={() => onOpenRecent(run.run_id)} title={run.run_id}>
              <span className="t">
                <span className={cx('status-dot', dotTone(run.status))} />
                {run.title}
              </span>
              <span className="m">
                {money(run.amount)} · {timeAgo(run.at)}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="sidebar-foot">
        <button className="cmdk-hint" onClick={onPalette} aria-label="Open command palette">
          <Command size={15} />
          <span className="lbl">Find an action</span>
          <span className="kbd">Ctrl K</span>
        </button>
        <p className="motto">
          <strong>Evidence before action.</strong>
          Comparable cases. Clear uncertainty. A handler stays in control.
        </p>
      </div>
    </aside>
  )
}
