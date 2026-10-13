import { useId, useState, type ReactNode } from 'react'
import type { FilterState, FormState } from '../lib/claimForm'
import { cx } from '../lib/format'
import { FIELDS, OUTCOMES, TYPES, compareCaption, isEmpty, parseDocuments, type Field } from '../lib/intakeView'
import { STATES } from '../lib/states'

// The last look before an investigation starts: every value that will be sent, as a labelled box that can still
// be changed. The exact JSON stays one click away, for anyone who wants to see the request itself.
type Hints = Partial<Record<Field, string>>

function Box({ id, label, hint, need, wide, children }: { id: string; label: string; hint?: string; need?: boolean; wide?: boolean; children: ReactNode }) {
  return (
    <div className={cx('ir-box', wide && 'wide', need && 'need')}>
      <label htmlFor={id}>{label}</label>
      {children}
      {need ? <span className="ir-flag need">Still needed</span> : hint ? <span className="ir-flag">{hint}</span> : null}
    </div>
  )
}

function StateSelect({ id, value, onChange, any }: { id: string; value: string; onChange: (value: string) => void; any?: string }) {
  const known = STATES.some(([code]) => code === value)
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{any ?? 'Choose a state'}</option>
      {!known && value && <option value={value}>{value} (not a state code)</option>}
      {STATES.map(([code, name]) => (
        <option key={code} value={code}>{name} ({code})</option>
      ))}
    </select>
  )
}

function TypeSelect({ id, value, onChange, any }: { id: string; value: string; onChange: (value: string) => void; any?: string }) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      {TYPES.map(([v, l]) => (
        <option key={v || 'none'} value={v}>{v === '' && any ? any : l}</option>
      ))}
    </select>
  )
}

/** The documents are typed as a list; the raw text is kept while typing so a trailing comma is not eaten. */
function DocsInput({ id, docs, onChange }: { id: string; docs: string[]; onChange: (docs: string[]) => void }) {
  const [raw, setRaw] = useState(docs.join(', '))
  return (
    <input
      id={id}
      type="text"
      value={raw}
      placeholder="police report, photos"
      onChange={(e) => {
        setRaw(e.target.value)
        onChange(parseDocuments(e.target.value))
      }}
    />
  )
}

export function IntakeReview({
  form, filters, hints = {}, today, json, onField, onDescription, onDocs, onFilter,
}: {
  form: FormState
  filters: FilterState
  hints?: Hints
  today: string
  json: string
  onField: (field: Exclude<Field, 'provided_documents'>, value: string) => void
  onDescription: (value: string) => void
  onDocs: (docs: string[]) => void
  onFilter: (patch: Partial<FilterState>) => void
}) {
  const uid = useId()
  const id = (name: string) => `${uid}-${name}`
  const need = (f: Field) => !FIELDS[f].optional && isEmpty(form, f)
  const number = (f: Exclude<Field, 'provided_documents'>, step: string, label: string) => (
    <Box id={id(f)} label={label} hint={hints[f]} need={need(f)}>
      <input id={id(f)} type="number" inputMode="decimal" min={0} step={step} value={form[f]} onChange={(e) => onField(f, e.target.value)} />
    </Box>
  )
  const shortDescription = form.description.trim().length < 10

  return (
    <div className="ir">
      <section aria-labelledby={id('claim')}>
        <h4 className="ir-h" id={id('claim')}>The claim</h4>
        <div className="ir-grid">
          <Box id={id('claim_type')} label="Claim type" hint={hints.claim_type}>
            <TypeSelect id={id('claim_type')} value={form.claim_type} onChange={(v) => onField('claim_type', v)} any="Auto-detect from the description" />
          </Box>
          <Box id={id('state')} label="State" hint={hints.state} need={need('state')}>
            <StateSelect id={id('state')} value={form.state} onChange={(v) => onField('state', v)} />
          </Box>
          {number('claim_amount', '0.01', 'Claim amount (USD)')}
          {number('deductible', '0.01', 'Deductible (USD)')}
          <Box id={id('incident_date')} label="Incident date" hint={hints.incident_date} need={need('incident_date')}>
            <input id={id('incident_date')} type="date" max={today} value={form.incident_date} onChange={(e) => onField('incident_date', e.target.value)} />
          </Box>
          <Box id={id('claim_filed_date')} label="Filing date" hint={hints.claim_filed_date} need={need('claim_filed_date')}>
            <input id={id('claim_filed_date')} type="date" min={form.incident_date || undefined} max={today} value={form.claim_filed_date} onChange={(e) => onField('claim_filed_date', e.target.value)} />
          </Box>
          {number('policyholder_tenure_years', '0.1', 'Policyholder tenure (years)')}
          {number('previous_claims_count', '1', 'Earlier claims')}
          <Box id={id('provided_documents')} label="Documents received (separate with commas)" hint={hints.provided_documents} wide>
            <DocsInput id={id('provided_documents')} docs={form.provided_documents} onChange={onDocs} />
          </Box>
          <Box id={id('description')} label="What happened" need={shortDescription} wide>
            <textarea id={id('description')} rows={3} maxLength={6000} value={form.description} onChange={(e) => onDescription(e.target.value)} />
          </Box>
        </div>
      </section>

      <section aria-labelledby={id('compare')}>
        <h4 className="ir-h" id={id('compare')}>Compared against</h4>
        <div className="ir-grid">
          <Box id={id('f-type')} label="Claim type">
            <TypeSelect id={id('f-type')} value={filters.claim_type} onChange={(v) => onFilter({ claim_type: v as FilterState['claim_type'] })} any="Same as the claim" />
          </Box>
          <Box id={id('f-state')} label="State">
            <StateSelect id={id('f-state')} value={filters.state} onChange={(v) => onFilter({ state: v })} any="Any state" />
          </Box>
          <Box id={id('f-status')} label="Outcome">
            <select id={id('f-status')} value={filters.claim_status} onChange={(e) => onFilter({ claim_status: e.target.value as FilterState['claim_status'] })}>
              {OUTCOMES.map(([v, l]) => (
                <option key={v || 'settled'} value={v}>{l}</option>
              ))}
            </select>
          </Box>
          <span aria-hidden="true" />
          <Box id={id('f-min-amount')} label="Amount from (USD)">
            <input id={id('f-min-amount')} type="number" inputMode="decimal" min={0} value={filters.min_amount} onChange={(e) => onFilter({ min_amount: e.target.value })} />
          </Box>
          <Box id={id('f-max-amount')} label="Amount up to (USD)">
            <input id={id('f-max-amount')} type="number" inputMode="decimal" min={0} value={filters.max_amount} onChange={(e) => onFilter({ max_amount: e.target.value })} />
          </Box>
          <Box id={id('f-min-prior')} label="Earlier claims, at least">
            <input id={id('f-min-prior')} type="number" inputMode="numeric" min={0} step={1} value={filters.min_previous_claims} onChange={(e) => onFilter({ min_previous_claims: e.target.value })} />
          </Box>
          <Box id={id('f-max-prior')} label="Earlier claims, at most">
            <input id={id('f-max-prior')} type="number" inputMode="numeric" min={0} step={1} value={filters.max_previous_claims} onChange={(e) => onFilter({ max_previous_claims: e.target.value })} />
          </Box>
        </div>
        <p className="ir-caption" aria-live="polite">{compareCaption(filters)}</p>
      </section>

      <details className="ir-json">
        <summary>Show the exact request as JSON</summary>
        <pre>{json}</pre>
      </details>
    </div>
  )
}
