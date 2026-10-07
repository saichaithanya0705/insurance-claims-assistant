import { useState, type ReactNode } from 'react'
import { cx } from '../lib/format'
import { CONTRIBUTION_SERIES, compactNumber, formatDuration, niceCeil, ticksTo } from '../lib/trace'

/* ==========================================================================
   Chart primitives. Marks are thin and capped, gridlines are hairlines, values live in text
   tokens (never in the series colour), every chart has a table twin, and hover and keyboard
   focus show the same detail. Tooltips add to what is already labelled; they never gate it.
   ========================================================================== */

export interface TableSpec {
  columns: string[]
  rows: (string | number | null)[][]
}

function TableView({ table }: { table: TableSpec }) {
  return (
    <div className="chart-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {table.columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell ?? '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ChartFrame({ title, subtitle, table, legend, children }: { title: string; subtitle?: string; table: TableSpec; legend?: ReactNode; children: ReactNode }) {
  const [view, setView] = useState<'chart' | 'table'>('chart')
  return (
    <figure className="chart-frame">
      <figcaption className="chart-head">
        <div>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="chart-toggle" role="group" aria-label={`${title}: view`}>
          <button type="button" className={cx(view === 'chart' && 'on')} aria-pressed={view === 'chart'} onClick={() => setView('chart')}>
            Chart
          </button>
          <button type="button" className={cx(view === 'table' && 'on')} aria-pressed={view === 'table'} onClick={() => setView('table')}>
            Table
          </button>
        </div>
      </figcaption>
      {view === 'chart' ? (
        <>
          {legend}
          {children}
        </>
      ) : (
        <TableView table={table} />
      )}
    </figure>
  )
}

/* ---------- Columns over time (one series, so no legend: the title names it) ---------- */
export interface ColumnDatum {
  key: string
  label: string
  value: number
  /** Shown in the readout only. */
  failed?: number
}

const roundedTop = (x: number, y: number, w: number, h: number, radius: number) => {
  const r = Math.max(0, Math.min(radius, w / 2, h))
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`
}

export function ColumnChart({ data, unit = 'queries', height = 176, axisLabel }: { data: ColumnDatum[]; unit?: string; height?: number; axisLabel: (datum: ColumnDatum, index: number) => string }) {
  const [active, setActive] = useState<number | null>(null)
  const width = 640
  const pad = { left: 34, right: 8, top: 12, bottom: 26 }
  const max = niceCeil(Math.max(1, ...data.map((d) => d.value)))
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom
  const slot = innerW / Math.max(data.length, 1)
  const barW = Math.min(24, slot * 0.62)
  const y = (value: number) => pad.top + innerH - (value / max) * innerH
  const every = Math.max(1, Math.ceil(data.length / 6))
  const peak = data.reduce((best, d, i) => (d.value > (data[best]?.value ?? -1) ? i : best), 0)
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="group" aria-label={`${unit} per period`}>
        {ticksTo(max, 2).map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} className={tick === 0 ? 'chart-axis' : 'chart-grid'} />
            <text x={pad.left - 6} y={y(tick) + 4} textAnchor="end" className="chart-tick">
              {compactNumber(tick)}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const center = pad.left + slot * i + slot / 2
          const h = d.value > 0 ? Math.max((d.value / max) * innerH, 2) : 0
          return (
            <g
              key={d.key}
              tabIndex={0}
              role="img"
              aria-label={`${d.label}: ${d.value} ${unit}${d.failed ? `, ${d.failed} failed` : ''}`}
              className={cx('chart-col', active === i && 'on')}
              onMouseEnter={() => setActive(i)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
            >
              <rect x={center - slot / 2} y={pad.top} width={slot} height={innerH + pad.bottom - 6} className="chart-hit" />
              {h > 0 && <path d={roundedTop(center - barW / 2, y(d.value), barW, h, 4)} className="chart-bar" />}
              {d.value > 0 && i === peak && data.length > 1 && (
                <text x={center} y={y(d.value) - 5} textAnchor="middle" className="chart-value">
                  {d.value}
                </text>
              )}
              {i % every === 0 && (
                <text x={center} y={height - 8} textAnchor="middle" className="chart-tick">
                  {axisLabel(d, i)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {active !== null && data[active] && (
        <div className="chart-tip" role="status" style={{ left: `${((pad.left + slot * active + slot / 2) / width) * 100}%` }}>
          <strong>
            {data[active].value} {data[active].value === 1 ? unit.replace(/ies$/, 'y').replace(/s$/, '') : unit}
          </strong>
          <span>{data[active].label}</span>
          {!!data[active].failed && <span className="tip-bad">{data[active].failed} failed</span>}
        </div>
      )}
    </div>
  )
}

/* ---------- Latency: a median bar with the 95th percentile as a tick ---------- */
export interface LatencyRow {
  key: string
  label: string
  p50: number | null
  p95: number | null
  count: number
  errors?: number
}

export function LatencyBars({ rows }: { rows: LatencyRow[] }) {
  const max = Math.max(1, ...rows.map((r) => r.p95 ?? r.p50 ?? 0))
  return (
    <div className="lat-rows" role="list">
      <div className="lat-key" aria-hidden="true">
        <span>
          <i className="lat-swatch" /> Median
        </span>
        <span>
          <i className="lat-swatch tick" /> 95th percentile
        </span>
      </div>
      {rows.map((row) => (
        <div
          key={row.key}
          role="listitem"
          tabIndex={0}
          className="lat-row"
          title={`${row.label}: median ${formatDuration(row.p50)}, 95th percentile ${formatDuration(row.p95)}, ${row.count} run${row.count === 1 ? '' : 's'}${row.errors ? `, ${row.errors} with errors` : ''}`}
        >
          <span className="lat-name">{row.label}</span>
          <span className="lat-track" aria-hidden="true">
            <span className="lat-fill" style={{ width: `${((row.p50 ?? 0) / max) * 100}%` }} />
            {row.p95 !== null && <i className="lat-tick" style={{ left: `${(row.p95 / max) * 100}%` }} />}
          </span>
          <span className="lat-val">
            {formatDuration(row.p50)}
            <small>p95 {formatDuration(row.p95)}</small>
          </span>
        </div>
      ))}
    </div>
  )
}

/* ---------- How three ranking methods each contributed to a comparable claim's score ----------
   Three series, so identity matters: the validated categorical slots 1 to 3 (see index.css), a
   legend that is always shown, and the ranks and total written out beside every bar. */
export interface ContributionRow {
  key: string
  label: string
  sublabel?: string
  total: number | null
  points: { keyword: number; feature: number; semantic: number } | null
  ranks: { keyword: number | null; feature: number | null; semantic: number | null }
}

export function ContributionLegend({ weights }: { weights?: Record<string, number | null> }) {
  return (
    <ul className="contrib-legend" aria-label="Ranking methods">
      {CONTRIBUTION_SERIES.map((s) => (
        <li key={s.id}>
          <i className={cx('contrib-swatch', s.swatch)} aria-hidden="true" /> {s.name}
          {typeof weights?.[s.id] === 'number' && <small> ×{weights[s.id]}</small>}
        </li>
      ))}
    </ul>
  )
}

export function ScoreContribution({ rows }: { rows: ContributionRow[] }) {
  const recorded = rows.filter((r) => r.points)
  const max = Math.max(1e-9, ...recorded.map((r) => (r.total ?? 0) || r.points!.keyword + r.points!.feature + r.points!.semantic))
  return (
    <div className="contrib" role="list">
      {rows.map((row) => {
        const total = row.total ?? (row.points ? row.points.keyword + row.points.feature + row.points.semantic : null)
        return (
          <div
            key={row.key}
            role="listitem"
            tabIndex={0}
            className="contrib-row"
            title={
              row.points
                ? `${row.label}: keyword ${row.points.keyword.toFixed(4)}, numeric ${row.points.feature.toFixed(4)}, semantic ${row.points.semantic.toFixed(4)}, total ${(total ?? 0).toFixed(4)}`
                : `${row.label}: total ${(total ?? 0).toFixed(4)} (per-method ranks were not recorded)`
            }
          >
            <span className="contrib-name">
              <b>{row.label}</b>
              {row.sublabel && <small>{row.sublabel}</small>}
            </span>
            <span className="contrib-bar" aria-hidden="true">
              {row.points ? (
                CONTRIBUTION_SERIES.map((s) => {
                  const value = row.points![s.id]
                  return value > 0 ? <i key={s.id} className={cx('contrib-seg', s.swatch)} style={{ width: `${(value / max) * 100}%` }} /> : null
                })
              ) : (
                <i className="contrib-seg unknown" style={{ width: `${((total ?? 0) / max) * 100}%` }} />
              )}
            </span>
            <span className="contrib-val">{total === null ? '—' : total.toFixed(4)}</span>
            <span className="contrib-ranks">
              {row.points ? (
                <>
                  keyword #{row.ranks.keyword ?? '—'} · numeric #{row.ranks.feature ?? '—'} · semantic {row.ranks.semantic ? `#${row.ranks.semantic}` : 'not ranked'}
                </>
              ) : (
                'Combined score only'
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}
