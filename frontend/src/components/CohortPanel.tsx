import type { CohortFigures, CohortStats } from '../lib/api'
import { pct } from '../lib/format'

// Figures come from DuckDB over the full dataset. Only the optional cross-check touches Synapt's
// retrieval, and it is labelled by where the cards really came from. Nothing here is evidence.
const NAMES: Record<string, string> = {
  exact: 'Same description',
  type_amount_history: 'Same type, amount and history',
  type: 'Same claim type',
}
const THIN = 'Too few claims for a stable figure'

const count = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US') : '—'
const days = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} days` : '—'
const range = (low: unknown, high: unknown) =>
  typeof low === 'number' && typeof high === 'number' && Number.isFinite(low) && Number.isFinite(high)
    ? `${low.toFixed(1)}–${high.toFixed(1)} days`
    : '—'
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

function CohortRow({ row }: { row: CohortFigures }) {
  const thin = row.sufficient === false
  return (
    <tr className={thin ? 'cohort-row-muted' : undefined}>
      <td>
        <span className="cohort-name">{NAMES[row.key] ?? 'Comparison group'}</span>
        <span className="cohort-definition">{row.definition}</span>
        {thin && <span className="cohort-thin">{THIN}</span>}
      </td>
      <td className="cohort-num" data-label="Number of claims">
        <span className="cohort-value">{count(row.claims)}</span>
      </td>
      <td className="cohort-num" data-label="Approved">
        <span className="cohort-value">{pct(row.approved_share)}</span>
      </td>
      <td className="cohort-num" data-label="Median days to settle">
        <span className="cohort-value">
          {days(row.median_days)}
          <span className="cohort-range">p25–p75 {range(row.p25_days, row.p75_days)}</span>
        </span>
      </td>
      <td className="cohort-num" data-label="Synthetic fraud flag">
        <span className="cohort-value">{pct(row.flag_rate)}</span>
      </td>
    </tr>
  )
}

function CrossCheck({ check }: { check: NonNullable<CohortStats['synapt_cross_check']> }) {
  // Only the two labels the server can send; anything else is not presented as Synapt. Live, the similar past claims come from
  // Synapt's ticket store; the local fallback copy still holds claim cards.
  const live = check.source === 'synapt'
  if (!live && check.source !== 'local_fallback') return null
  const cards = check.cards_returned
  const exact = check.in_exact_cohort
  const broad = check.in_type_amount_history_cohort
  return (
    <div className="cohort-check">
      <span className="cohort-check-label">Cross-check against retrieved past claims</span>
      <p>
        {live
          ? <>Of the {cards} similar past {plural(cards, 'claim', 'claims')} returned by Synapt's ticket store</>
          : <>Of the {cards} claim {plural(cards, 'card', 'cards')} returned by the local fallback copy, not Synapt</>}
        , {exact}{' '}
        {plural(exact, 'describes', 'describe')} this exact cohort and {broad}{' '}
        {plural(broad, 'is', 'are')} in the same type, amount and prior-claims bands.
      </p>
    </div>
  )
}

export function CohortPanel({ cohort }: { cohort?: CohortStats | null }) {
  // Runs saved before this panel existed have no cohort; the page simply omits it.
  if (!cohort) return null
  if (!cohort.available) {
    return (
      <p className="cohort-unavailable">
        Cohort statistics are not shown for this run{cohort.reason ? `: ${cohort.reason}` : '.'}
      </p>
    )
  }
  const rows = Array.isArray(cohort.cohorts) ? cohort.cohorts : []
  const notes = Array.isArray(cohort.notes) ? cohort.notes : []
  const dataset = typeof cohort.dataset_claims === 'number' ? ` over ${count(cohort.dataset_claims)} claims` : ''
  const timing = typeof cohort.elapsed_seconds === 'number' ? ` in ${cohort.elapsed_seconds.toFixed(1)} s` : ''
  return (
    <section className="cohort-panel" aria-labelledby="cohort-heading">
      <h3 className="cohort-heading" id="cohort-heading">How claims like this were settled</h3>
      <p className="cohort-desc">
        Exact statistics from the full dataset, computed by DuckDB. They describe past claims with similar
        details and do not decide, predict or assess coverage for this claim. "Number of claims" counts past
        claims in each group; it is not a money amount. The dataset is synthetic.
      </p>
      <table className="cohort-table">
        <thead>
          <tr>
            <th scope="col">Past claims compared</th>
            <th scope="col">Number of claims</th>
            <th scope="col">Approved</th>
            <th scope="col">Median days to settle</th>
            <th scope="col">Synthetic fraud flag</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <CohortRow key={row.key} row={row} />
          ))}
        </tbody>
      </table>
      {cohort.synapt_cross_check && <CrossCheck check={cohort.synapt_cross_check} />}
      <div className="cohort-footnote">
        <p>Computed by DuckDB{dataset}{timing}, not by Synapt.</p>
        {cohort.eligibility && <p>Counted: {cohort.eligibility}.</p>}
        {notes.map((note) => (
          <p key={note}>{note}</p>
        ))}
      </div>
    </section>
  )
}
