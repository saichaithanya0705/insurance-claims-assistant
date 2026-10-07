import { createContext, useCallback, useContext, useRef, useState, type HTMLAttributes, type PointerEvent, type ReactNode } from 'react'
import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useSpring, useTransform } from 'motion/react'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { cx } from '../lib/format'

/* ---------- 3D tilt surface ----------
   Pointer position drives a spring-damped rotateX/rotateY in a perspective
   container, plus a soft glare that follows the cursor. Purely decorative:
   content is static, and reduced-motion users get a flat surface. */
export function Tilt({ children, className, max = 6, glare = true }: { children: ReactNode; className?: string; max?: number; glare?: boolean }) {
  const reduce = useReducedMotion()
  const px = useMotionValue(0.5)
  const py = useMotionValue(0.5)
  const spring = { stiffness: 170, damping: 18, mass: 0.6 }
  const rotateX = useSpring(useTransform(py, [0, 1], [max, -max]), spring)
  const rotateY = useSpring(useTransform(px, [0, 1], [-max, max]), spring)
  const gx = useTransform(px, (v) => `${v * 100}%`)
  const gy = useTransform(py, (v) => `${v * 100}%`)
  const background = useMotionTemplate`radial-gradient(520px circle at ${gx} ${gy}, rgb(255 255 255 / 0.55), transparent 45%)`
  const move = (e: PointerEvent<HTMLDivElement>) => {
    if (reduce || e.pointerType !== 'mouse') return
    const box = e.currentTarget.getBoundingClientRect()
    px.set((e.clientX - box.left) / box.width)
    py.set((e.clientY - box.top) / box.height)
  }
  const reset = () => { px.set(0.5); py.set(0.5) }
  return (
    <div className={cx('tilt', className)} onPointerMove={move} onPointerLeave={reset}>
      <motion.div className="tilt-inner" style={reduce ? undefined : { rotateX, rotateY }}>
        {children}
        {glare && !reduce && <motion.span className="tilt-glare" aria-hidden="true" style={{ background }} />}
      </motion.div>
    </div>
  )
}

/* ---------- Score ring that draws itself; the number is static text ---------- */
export function ScoreRing({ value, size = 112, stroke = 10, tone = 'teal', children }: { value: number; size?: number; stroke?: number; tone?: string; children?: ReactNode }) {
  const radius = (size - stroke) / 2
  const fraction = Math.max(0, Math.min(1, value))
  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--track)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={`var(--${tone})`} strokeWidth={stroke} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          initial={{ pathLength: 0 }} animate={{ pathLength: fraction }} transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
        />
      </svg>
      <div className="score-ring-label">{children}</div>
    </div>
  )
}

/* ---------- Shared surfaces ---------- */
// Cards track the pointer in CSS variables so the border spotlight can follow it.
const spotlight = (e: PointerEvent<HTMLElement>) => {
  const box = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--mx', `${e.clientX - box.left}px`)
  e.currentTarget.style.setProperty('--my', `${e.clientY - box.top}px`)
}
export function Card({ children, className, spot = true, ...rest }: HTMLAttributes<HTMLElement> & { spot?: boolean; children: ReactNode }) {
  return <section className={cx('card', className)} onPointerMove={spot ? spotlight : undefined} {...rest}>{children}</section>
}

export const Pill = ({ tone, children, dot }: { tone?: string; children: ReactNode; dot?: boolean }) => (
  <span className={cx('pill', tone)}>
    {dot && <span className={cx('status-dot', tone)} aria-hidden="true" />}
    {children}
  </span>
)

/* ---------- Values are factual from the first render ---------- */
export function CountUp({ value, format = (v) => Math.round(v).toLocaleString('en-US') }: {
  value: number
  format?: (v: number) => string
  duration?: number
}) {
  return <span>{Number.isFinite(value) ? format(value) : 'Unavailable'}</span>
}

/* ---------- Static score gauge with threshold marker ---------- */
export function Gauge({ value, threshold, size = 180 }: { value: number; threshold?: number; size?: number }) {
  const stroke = 12
  const radius = (size - stroke) / 2
  const center = size / 2
  const arc = `M ${stroke / 2} ${center} A ${radius} ${radius} 0 0 1 ${size - stroke / 2} ${center}`
  const score = Math.max(0, Math.min(1, value))
  const angle = threshold !== undefined ? Math.PI * (1 - threshold) : 0
  const color = threshold !== undefined && value >= threshold ? 'var(--amber)' : 'var(--teal)'
  return (
    <svg width={size} height={size / 2 + 12} viewBox={`0 0 ${size} ${size / 2 + 12}`} role="img" aria-label={`Dataset flag score ${(value * 100).toFixed(1)} percent${threshold !== undefined ? `; review threshold ${(threshold * 100).toFixed(1)} percent` : ''}`}>
      <path d={arc} fill="none" stroke="var(--track)" strokeWidth={stroke} strokeLinecap="round" />
      {score > 0 && <path d={arc} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" pathLength={1} strokeDasharray={`${score} 1`} />}
      {threshold !== undefined && (
        <line x1={center + Math.cos(angle) * (radius - 12)} y1={center - Math.sin(angle) * (radius - 12)} x2={center + Math.cos(angle) * (radius + 8)} y2={center - Math.sin(angle) * (radius + 8)} stroke="var(--text)" strokeWidth={2} />
      )}
    </svg>
  )
}

/* ---------- Static evaluation ring ---------- */
export function Ring({ value, size = 92, stroke = 9, tone = 'teal' }: { value: number; size?: number; stroke?: number; tone?: 'teal' | 'amber' | 'rose' }) {
  const radius = (size - stroke) / 2
  const fraction = Math.max(0, Math.min(1, value))
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--track)" strokeWidth={stroke} />
      {fraction > 0 && <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={`var(--${tone})`} strokeWidth={stroke} strokeLinecap="round" pathLength={1} strokeDasharray={`${fraction} 1`} />}
    </svg>
  )
}

/* ---------- Static measured comparison bar ---------- */
export const Bar = ({ value, tone }: { value: number; tone?: 'muted' | 'amber'; delay?: number }) => (
  <div className="bar-track" aria-hidden="true">
    <div className={cx('bar-fill', tone)} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
  </div>
)

/* Short staggered entrance on mount. Values are final from the first frame; only position and opacity ease in. */
export const listVariants = { hidden: {}, show: { transition: { staggerChildren: 0.045, delayChildren: 0.05 } } }
export const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { type: 'spring' as const, stiffness: 260, damping: 26 } },
}
export const Background = () => null

/* ---------- Toasts ---------- */
type ToastTone = 'ok' | 'err' | 'info'
interface ToastItem {
  id: number
  message: string
  tone: ToastTone
}
const ToastContext = createContext<(message: string, tone?: ToastTone) => void>(() => {})
export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const seq = useRef(0)
  const push = useCallback((message: string, tone: ToastTone = 'ok') => {
    const id = ++seq.current
    setItems((list) => [...list.slice(-3), { id, message, tone }])
    setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), 4800)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className={cx('toast', t.tone)}>
              {t.tone === 'ok' ? <CheckCircle2 size={16} /> : t.tone === 'err' ? <AlertTriangle size={16} /> : <Info size={16} />}
              <span>{t.message}</span>
            </div>
          ))}
      </div>
    </ToastContext.Provider>
  )
}

export const ErrorBox = ({ message }: { message?: string | null }) =>
  message ? (
    <div className="error" role="alert">
      <AlertTriangle size={16} />
      <span>{message}</span>
    </div>
  ) : null

/* ---------- Generic key/value view for loosely-typed payloads ---------- */
export function DataView({ value, depth = 0 }: { value: unknown; depth?: number }): ReactNode {
  if (value === null || value === undefined) return <span style={{ color: 'var(--text-3)' }}>Unavailable</span>
  if (Array.isArray(value)) {
    if (!value.length) return <span style={{ color: 'var(--text-3)' }}>None returned</span>
    return (
      <ul className="plain-list">
        {value.map((item, i) => (
          <li key={i}>{item && typeof item === 'object' ? <DataView value={item} depth={depth + 1} /> : String(item)}</li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (!entries.length) return <span style={{ color: 'var(--text-3)' }}>No details returned</span>
    return (
      <dl className="kv">
        {entries.map(([key, item]) =>
          item && typeof item === 'object' ? (
            <details key={key} className="disclose" open={depth < 1}>
              <summary>{key.replace(/_/g, ' ')}</summary>
              <div className="disclose-body">
                <DataView value={item} depth={depth + 1} />
              </div>
            </details>
          ) : (
            <div key={key}>
              <dt>{key.replace(/_/g, ' ')}</dt>
              <dd>{typeof item === 'boolean' ? (item ? 'Yes' : 'No') : String(item)}</dd>
            </div>
          ),
        )}
      </dl>
    )
  }
  return <>{String(value)}</>
}
