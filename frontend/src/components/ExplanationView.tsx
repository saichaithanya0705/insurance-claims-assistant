import { useEffect, useState, type ReactNode } from 'react'
import { AlertTriangle, Check, CircleDashed, Link2, Minus, Network, RefreshCw, ShieldCheck, X } from 'lucide-react'
import { api, type ExplainEstimateTask, type ExplainLayer, type ExplainLineage, type ExplainSource, type Explanation } from '../lib/api'
import { cx, label, money, num, pct } from '../lib/format'
import { CONTRIBUTION_SERIES, formatDuration } from '../lib/trace'
import { Bar, Card, ErrorBox, Pill } from './ui'
import { STAGES } from './Pipeline'
import { ChartFrame, ContributionLegend, ScoreContribution } from './Charts'

const KIND_META: Record<string, { label: string; tone?: string }> = {
  ai: { label: 'AI model', tone: 'violet' },
  rules: { label: 'Fixed rules', tone: 'sky' },
  search: { label: 'Search and ranking', tone: 'teal' },
  statistics: { label: 'Statistical models', tone: 'amber' },
  human: { label: 'A person', tone: 'teal' },
  off: { label: 'Not run' },
}
const TIER_TONE: Record<string, string> = { critical: 'rose', high: 'amber', medium: 'sky', low: 'teal' }
const CATEGORY_LABEL: Record<string, string> = { claim: 'Submitted claim', procedure: 'Handling procedure', history: 'Comparable claim', lesson: 'Reviewed lesson', unknown: 'Unresolved source' }
const FINDING_TONE: Record<string, string> = { fact: 'teal', gap: 'amber', risk_indicator: 'amber', contradiction: 'rose', limitation: 'violet' }

const Section = ({ id, title, lead, children }: { id: string; title: string; lead?: string; children: ReactNode }) => (
  <section className="xp-section" id={id} aria-labelledby={`${id}-h`}>
    <h3 id={`${id}-h`}>{title}</h3>
    {lead && <p className="section-desc">{lead}</p>}
    <Card spot={false}>
      <div className="card-body">{children}</div>
    </Card>
  </section>
)

/* ---------- Generation ---------- */
function Steps({ data }: { data: Explanation }) {
  const longest = Math.max(1, ...data.pipeline.map((s) => s.duration_ms ?? 0))
  return (
    <ol className="xp-steps">
      {data.pipeline.map((stage, index) => {
        const Icon = STAGES.find((s) => s.key === stage.stage)?.icon ?? CircleDashed
        const meta = KIND_META[stage.kind] ?? { label: label(stage.kind) }
        return (
          <li key={stage.stage} className={cx('xp-step', stage.status)}>
            <span className="xp-step-n" aria-hidden="true">
              <Icon size={16} />
            </span>
            <div className="xp-step-body">
              <div className="xp-step-head">
                <h4>
                  <span className="xp-index">{index + 1}</span> {stage.title}
                </h4>
                <div className="chips">
                  <Pill tone={meta.tone}>{meta.label}</Pill>
                  {stage.status === 'waiting' && <Pill tone="amber">Waiting for a handler</Pill>}
                  {stage.status === 'pending' && <Pill tone="sky">In progress</Pill>}
                  {stage.status === 'skipped' && <Pill>Not run</Pill>}
                  {stage.duration_ms !== null && <span className="xp-dur">{formatDuration(stage.duration_ms)}</span>}
                </div>
              </div>
              <p className="xp-what">{stage.what}</p>
              <p className="xp-how">{stage.how}</p>
              <div className="xp-io">
                <div>
                  <small>Reads</small>
                  <ul>
                    {stage.inputs.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <small>Produces</small>
                  <ul>
                    {stage.outputs.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              </div>
              {stage.duration_ms !== null && stage.duration_ms >= 1 && <Bar value={stage.duration_ms / longest} />}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/* ---------- Lineage ---------- */
function SourceChip({ source, onSource }: { source: ExplainSource; onSource?: (id: string) => void }) {
  const text = source.label
  const content = (
    <>
      <Link2 size={12} aria-hidden="true" /> {text}
      {text !== CATEGORY_LABEL[source.category] && <small>{CATEGORY_LABEL[source.category] ?? source.category}</small>}
    </>
  )
  const title = source.excerpt ? `${CATEGORY_LABEL[source.category] ?? source.category}: “${source.excerpt}”` : (CATEGORY_LABEL[source.category] ?? source.category)
  return onSource && source.category !== 'unknown' ? (
    <button type="button" className={cx('xp-src', `cat-${source.category}`)} title={title} onClick={() => onSource(source.source_id)}>
      {content}
    </button>
  ) : (
    <span className={cx('xp-src', `cat-${source.category}`)} title={title}>
      {content}
    </span>
  )
}

function Lineage({ rows, onSource }: { rows: ExplainLineage[]; onSource?: (id: string) => void }) {
  const groups = [
    { title: 'Findings', items: rows.filter((r) => r.type === 'finding') },
    { title: 'Recommendations', items: rows.filter((r) => r.type === 'recommendation') },
  ]
  return (
    <div className="xp-lineage">
      {groups.map((group) => (
        <div key={group.title}>
          <h4 className="mini-title">
            {group.title} · {group.items.length}
          </h4>
          {group.items.length === 0 && <div className="small-empty">None were produced.</div>}
          <ul>
            {group.items.map((row) => (
              <li key={`${row.type}-${row.index}`} className={cx('xp-line', row.unsupported && 'bad')}>
                <div className="xp-line-head">
                  <Pill tone={row.type === 'finding' ? FINDING_TONE[row.kind] : 'teal'}>{row.type === 'finding' ? label(row.kind) : row.kind}</Pill>
                  <small>{row.method === 'ai' ? 'written by the AI model' : 'written by fixed rules'}</small>
                  {row.unsupported && (
                    <Pill tone="rose">
                      <AlertTriangle size={11} /> No source cited
                    </Pill>
                  )}
                </div>
                <p>{row.text}</p>
                {row.sources.length > 0 ? (
                  <div className="xp-sources" aria-label="Sources behind this statement">
                    {row.sources.map((s) => (
                      <SourceChip key={s.source_id} source={s} onSource={onSource} />
                    ))}
                  </div>
                ) : (
                  row.type === 'finding' && row.kind === 'limitation' && <small className="txt-muted">A limitation states what is not known, so it needs no source.</small>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

/* ---------- Retrieval ---------- */
function Retrieval({ data }: { data: Explanation['retrieval'] }) {
  const weights = Object.fromEntries(data.methods.map((m) => [m.id, m.weight]))
  const c = data.candidates
  const rows = data.ranked
  return (
    <>
      <div className="xp-methods">
        {data.methods.map((m, i) => (
          <div key={m.id} className="xp-method">
            <h4>
              <i className={cx('contrib-swatch', CONTRIBUTION_SERIES[i].swatch)} aria-hidden="true" /> {m.name}
              {typeof m.weight === 'number' && <small>weight ×{m.weight}</small>}
            </h4>
            <p>{m.how}</p>
          </div>
        ))}
      </div>
      <p className="xp-formula">
        <b>Combined score</b> <code>{data.formula}</code> Each term is a reciprocal rank, so being near the top of any list helps, and no single list can dominate.
      </p>
      <dl className="kv xp-pool">
        <div>
          <dt>Comparison pool</dt>
          <dd>{data.pool}</dd>
        </div>
        {Object.keys(data.filters).length > 0 && (
          <div>
            <dt>Filters applied</dt>
            <dd>{Object.entries(data.filters).map(([k, v]) => `${label(k)}: ${String(v)}`).join(' · ')}</dd>
          </div>
        )}
        {c && (
          <div>
            <dt>Candidates</dt>
            <dd>
              {c.sql_candidates ?? '—'} chosen by exact filters and numeric closeness
              {c.semantic_added ? ` + ${c.semantic_added} added from the knowledge store's own ranking` : ''} → {c.pool_size ?? '—'} ranked → {rows.filter((r) => r.surfaced_by !== 'semantic').length} shown as closest
              {rows.some((r) => r.surfaced_by === 'semantic') ? ` + ${rows.filter((r) => r.surfaced_by === 'semantic').length} related by meaning` : ''}
            </dd>
          </div>
        )}
        {data.semantic && (
          <div>
            <dt>Semantic matches</dt>
            <dd>
              {data.semantic.semantic_candidates ?? 0} claim cards matched · {data.semantic.semantic_eligible ?? 0} eligible under the filters · {data.semantic.semantic_in_results ?? 0} in the results
            </dd>
          </div>
        )}
      </dl>
      {data.note && (
        <div className="notice" role="note">
          <AlertTriangle size={16} />
          <span>{data.note}</span>
        </div>
      )}
      {rows.length === 0 ? (
        <div className="small-empty">No comparable claims matched the filters, so nothing was ranked.</div>
      ) : (
        <ChartFrame
          title="How each comparable claim scored"
          subtitle="Bar length is the combined score; each colour is one method’s share of it"
          legend={<ContributionLegend weights={weights} />}
          table={{
            columns: ['Rank', 'Claim', 'Keyword rank', 'Numeric rank', 'Semantic rank', 'Keyword', 'Numeric', 'Semantic', 'Combined'],
            rows: rows.map((r) => [r.rank, r.claim_id, r.keyword_rank, r.feature_rank, r.semantic_rank, r.points?.keyword.toFixed(4) ?? null, r.points?.feature.toFixed(4) ?? null, r.points?.semantic.toFixed(4) ?? null, r.total?.toFixed(4) ?? null]),
          }}
        >
          <ScoreContribution
            rows={rows.map((r) => ({
              key: r.claim_id,
              label: `#${r.rank} ${r.claim_id}`,
              sublabel: `${label(r.claim_type)} · ${r.state ?? '—'} · ${money(r.claim_amount ?? undefined)} · ${label(r.outcome)}${r.surfaced_by === 'semantic' ? ' · related by meaning' : ''}`,
              total: r.total,
              points: r.points,
              ranks: { keyword: r.keyword_rank, feature: r.feature_rank, semantic: r.semantic_rank },
            }))}
          />
        </ChartFrame>
      )}
      {data.knowledge_queries && data.knowledge_queries.length > 0 && (
        <details className="disclose">
          <summary>
            <Network size={14} /> What the knowledge store was asked · {data.knowledge_queries.length}
          </summary>
          <div className="disclose-body">
            <ul className="xp-queries">
              {data.knowledge_queries.map((q, i) => (
                <li key={i}>
                  <b>{label(q.purpose)}</b> <span className="mono">{q.tool}</span> · top {q.top_k ?? '—'} · {formatDuration(q.duration_ms)}
                  <code>{q.query}</code>
                </li>
              ))}
            </ul>
            <p className="footnote">Queries are built from claim-type words and banded values, never from the claim’s free text.</p>
          </div>
        </details>
      )}
      <p className="footnote">Scores are ranks, not probabilities. A similar claim’s outcome does not establish coverage or fraud for this claim.</p>
    </>
  )
}

/* ---------- Priority ---------- */
function Priority({ data }: { data: Explanation['priority'] }) {
  if (typeof data.score !== 'number') return <div className="small-empty">This run was not scored for handling priority.</div>
  const tone = TIER_TONE[data.tier ?? 'low'] ?? 'teal'
  return (
    <>
      <div className="xp-meter" role="img" aria-label={`Priority score ${data.score} of 100, tier ${data.tier}`}>
        <div className="xp-meter-track">
          <i className={tone} style={{ width: `${data.score}%` }} />
          {data.tiers
            .filter((t) => t.from > 0)
            .map((t) => (
              <span key={t.tier} className="xp-meter-tick" style={{ left: `${t.from}%` }} />
            ))}
        </div>
        <div className="xp-meter-labels" aria-hidden="true">
          {data.tiers
            .slice()
            .reverse()
            .map((t) => (
              <span key={t.tier} style={{ left: `${t.from}%` }}>
                {label(t.tier)} {t.from > 0 ? `≥ ${t.from}` : ''}
              </span>
            ))}
        </div>
      </div>
      <p className="xp-score-line">
        <b>{data.score}</b> / 100 · <Pill tone={tone}>{label(data.tier)}</Pill>
        {data.next_tier ? ` ${data.next_tier.points_needed} more point${data.next_tier.points_needed === 1 ? '' : 's'} would reach ${data.next_tier.tier}.` : ' Already in the highest tier.'}
      </p>
      <div className="chart-table-wrap">
        <table className="data-table xp-factors">
          <thead>
            <tr>
              <th scope="col">Factor</th>
              <th scope="col">Rule</th>
              <th scope="col">Points</th>
            </tr>
          </thead>
          <tbody>
            {data.factors.map((f) => (
              <tr key={f.id} className={cx(!f.applied && 'off')}>
                <td>
                  {f.applied ? <Check size={13} className="txt-ok" aria-label="Applied" /> : <Minus size={13} className="txt-muted" aria-label="Did not apply" />} {f.label}
                </td>
                <td>{f.rule}</td>
                <td className="num">
                  <b>{f.points}</b> / {f.max_points}
                  <Bar value={f.points / f.max_points} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.components.length > 0 && (
        <details className="disclose">
          <summary>Exactly why each point was awarded · {data.components.length}</summary>
          <ul className="components">
            {data.components.map((c, i) => (
              <li key={i}>
                <b className="mono">+{c.points}</b>
                <span>{c.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.policy && <p className="footnote">{data.policy}</p>}
    </>
  )
}

/* ---------- Estimates ---------- */
const effectText = (value: number, unit: string) => `${value >= 0 ? '+' : '−'}${unit === 'USD' ? money(Math.abs(value)) : `${num(Math.abs(value), unit === 'score' ? 3 : 1)} ${unit}`}`

// Smallest effect worth listing, per unit; the amount model varies only by claim type, so most
// features legitimately contribute nothing and listing "+$0" rows would be noise.
const NEGLIGIBLE: Record<string, number> = { USD: 0.5, days: 0.05, score: 0.0005 }

function Estimate({ task }: { task: ExplainEstimateTask }) {
  const drivers = task.drivers.filter((d) => Math.abs(d.effect) >= (NEGLIGIBLE[task.unit] ?? 0))
  const headline = !task.available
    ? 'Unavailable'
    : task.id === 'fraud'
      ? pct(task.score ?? undefined)
      : task.unit === 'USD'
        ? money(task.estimate ?? undefined)
        : `${num(task.estimate, 1)} days`
  const detail = !task.available
    ? task.reason
    : task.id === 'fraud'
      ? `${task.review_signal ? 'Above' : 'Below'} the ${pct(task.review_threshold ?? undefined)} review threshold`
      : task.interval
        ? `90% interval ${task.unit === 'USD' ? money(task.interval[0]) : `${num(task.interval[0], 0)} days`} to ${task.unit === 'USD' ? money(task.interval[1]) : `${num(task.interval[1], 0)} days`}`
        : null
  return (
    <article className="xp-est">
      <h4>{task.title}</h4>
      <div className="xp-est-val">{headline}</div>
      {detail && <p className="cap">{detail}</p>}
      {task.available && drivers.length === 0 && <p className="footnote">Nothing about this claim moved the estimate away from a typical claim’s.</p>}
      {drivers.length > 0 && (
        <>
          <h5 className="mini-title">What moved this estimate</h5>
          <ul className="effects">
            {drivers.map((d) => (
              <li key={d.feature}>
                <span>
                  {label(d.feature)}: <b>{String(d.value)}</b> <small>(typical {String(d.typical_value)})</small>
                </span>
                <b className={d.effect >= 0 ? 'up' : 'down'}>{effectText(d.effect, task.unit)}</b>
              </li>
            ))}
          </ul>
          {task.driver_method && <p className="footnote">{task.driver_method}</p>}
        </>
      )}
      {task.learned.length > 0 && (
        <details className="disclose">
          <summary>What the model learned overall</summary>
          <div className="disclose-body">
            <ul className="effects plain">
              {task.learned.map((line) => (
                <li key={line}>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
            {task.learned_method && <p className="footnote">{task.learned_method}</p>}
          </div>
        </details>
      )}
    </article>
  )
}

/* ---------- Evaluation ---------- */
const stateTone = (state?: string) => (['passed', 'accepted', 'completed'].includes(state ?? '') ? 'teal' : ['failed', 'revision_requested'].includes(state ?? '') ? 'rose' : state === 'pending' ? 'sky' : undefined)
const stateText: Record<string, string> = { passed: 'Passed', failed: 'Failed', accepted: 'Accepted', revision_requested: 'Revision requested', awaiting: 'Awaiting a handler', completed: 'Completed', pending: 'In progress', skipped: 'Not run', unavailable: 'Unavailable' }

function Ratio({ title, done, total, note }: { title: string; done: number; total: number; note?: string }) {
  return (
    <div className="xp-ratio">
      <span>{title}</span>
      <Bar value={total ? done / total : 0} />
      <b>
        {done} / {total}
      </b>
      {note && <small>{note}</small>}
    </div>
  )
}

function Layer({ layer, admin }: { layer: ExplainLayer; admin: boolean }) {
  const kind = KIND_META[layer.kind] ?? { label: label(layer.kind) }
  return (
    <article className={cx('xp-layer', layer.id)}>
      <header>
        <h4>{layer.title}</h4>
        <div className="chips">
          <Pill tone={kind.tone}>{kind.label}</Pill>
          {layer.gate && <Pill tone="amber">Gate</Pill>}
          {layer.state && <Pill tone={stateTone(layer.state)}>{stateText[layer.state] ?? label(layer.state)}</Pill>}
        </div>
      </header>
      <p className="xp-layer-lead">{layer.summary}</p>

      {layer.id === 'validation' && (
        <>
          <ul className="xp-checks">
            {(layer.checks ?? []).map((c) => (
              <li key={c.id} className={c.passed ? 'ok' : 'bad'}>
                <span className="xp-check-icon" aria-label={c.passed ? 'Passed' : 'Failed'}>
                  {c.passed ? <Check size={13} /> : <X size={13} />}
                </span>
                <span>
                  <b>{c.label}</b>
                  <small>{c.description}</small>
                </span>
                <span className="xp-check-n">{c.inspected === 0 ? 'nothing to check' : c.failed ? `${c.failed} of ${c.inspected} failed` : `${c.inspected} checked`}</span>
              </li>
            ))}
          </ul>
          {!!layer.issues?.length && (
            <ul className="reasons">
              {layer.issues.map((issue) => (
                <li key={issue}>
                  <AlertTriangle size={14} />
                  <span>{issue}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="footnote">
            Checks {layer.checks_source}. {layer.rechecked && (layer.rechecked.matches_saved ? 'Re-running them now gives the same verdict as the one saved.' : 'Re-running them now gives a different verdict from the one saved.')} {layer.scope && `Scope: ${layer.scope}.`}
          </p>
        </>
      )}

      {layer.id === 'grounding' && layer.metrics && (
        <>
          <div className="xp-ratios">
            <Ratio title="Substantive findings that cite a source" done={layer.metrics.substantive_cited} total={layer.metrics.substantive_findings} />
            <Ratio title="Citations that resolve to supplied evidence" done={layer.metrics.citations_resolved} total={layer.metrics.citations} />
            <Ratio title="Recommendations that cite a source" done={layer.metrics.recommendations_cited} total={layer.metrics.recommendations} />
            <Ratio title="Retrieved outside sources the brief draws on" done={layer.metrics.external_sources_cited} total={layer.metrics.external_sources_available} note="Unused sources were retrieved but not cited." />
          </div>
        </>
      )}

      {layer.id === 'judge' && (
        <>
          {layer.state === 'completed' ? (
            <>
              <div className="chips" role="list" aria-label="Independent review checks">
                {([['Grounded in the cited evidence', layer.grounded], ['Stays inside the decision boundary', layer.boundary_respected], ['Recommendations follow the findings', layer.recommendations_supported]] as const).map(([name, ok]) => (
                  <span key={name} role="listitem" className={cx('check', !ok && 'fail')}>
                    {ok ? <Check size={11} /> : <AlertTriangle size={11} />} {name}
                  </span>
                ))}
              </div>
              {typeof layer.score === 'number' && (
                <div className="xp-ratio">
                  <span>Quality score</span>
                  <span className="xp-pass-meter">
                    <Bar value={layer.score} tone={layer.score >= 0.7 ? undefined : 'amber'} />
                    <i style={{ left: '70%' }} aria-hidden="true" />
                  </span>
                  <b>{num(layer.score, 2)}</b>
                  <small>Passing line 0.70</small>
                </div>
              )}
              {layer.verdict && <p className="xp-verdict">{layer.verdict}</p>}
              {!!layer.issues?.length && (
                <ul className="reasons">
                  {layer.issues.map((issue) => (
                    <li key={issue}>
                      <AlertTriangle size={14} />
                      <span>{issue}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className="xp-verdict">{layer.reason ?? 'No verdict is available for this brief.'}</p>
          )}
          {layer.criteria && <p className="footnote">{layer.criteria}</p>}
          {admin && layer.model && (
            <p className="footnote">
              Reviewed by <span className="mono">{layer.model}</span>
              {layer.independent === false ? ' — the same model that wrote the brief, so not independent.' : ' — a different model from the author.'}
            </p>
          )}
        </>
      )}

      {layer.id === 'human' && (
        <>
          {layer.note && <p className="xp-verdict">“{layer.note}”</p>}
          <p className="footnote">Accepting or requesting a revision records a judgement about the brief only. It never approves, denies or pays the claim.</p>
        </>
      )}

      {layer.id === 'suite' && (
        <>
          <Ratio title="Golden claims passed" done={typeof layer.passed === 'number' ? layer.passed : 0} total={layer.total ?? 0} />
          {layer.judge_expected_metrics ? <p className="footnote">Model-graded metrics passed: {layer.judge_passed_metrics ?? 0} of {layer.judge_expected_metrics}.</p> : <p className="footnote">Model-graded metrics: {label(layer.judge_status)}.</p>}
          {layer.scope && <p className="footnote">{layer.scope}</p>}
        </>
      )}
    </article>
  )
}

/* ======================================================================
   Body (presentational) and loader
   ====================================================================== */
export function ExplanationBody({ data, admin = false, idPrefix = 'xp', onOpenTrace, onSource }: { data: Explanation; admin?: boolean; idPrefix?: string; onOpenTrace?: () => void; onSource?: (id: string) => void }) {
  const id = (name: string) => `${idPrefix}-${name}`
  const sections = [
    ['generation', 'Generation'],
    ['sources', 'Sources'],
    ['ranking', 'Comparable claims'],
    ['priority', 'Priority'],
    ['estimates', 'Estimates'],
    ['evaluation', 'Evaluation'],
    ['limits', 'Limits'],
  ] as const
  const timeline = data.timeline
  const longest = Math.max(1, ...(timeline?.stages.map((s) => s.duration_ms) ?? [1]))
  return (
    <div className="xp">
      <Card className="xp-hero" spot={false}>
        <div className="xp-hero-top">
          <div>
            <div className="eyebrow">How this brief was made</div>
            <p className="xp-headline">{data.headline}</p>
          </div>
          <div className="chips">
            <Pill tone={data.generation === 'ai' ? 'violet' : 'sky'}>{data.generation === 'ai' ? 'Drafted by an AI model' : 'Drafted by fixed rules (demonstration mode)'}</Pill>
            <Pill tone={data.status === 'failed' ? 'rose' : data.status === 'reviewed' ? 'teal' : 'amber'} dot>
              {label(data.status)}
            </Pill>
            {admin && onOpenTrace && (
              <button className="btn sm" type="button" onClick={onOpenTrace}>
                Open full trace
              </button>
            )}
          </div>
        </div>
        <p className="xp-promise">
          <ShieldCheck size={14} aria-hidden="true" /> {data.boundaries[0]}
        </p>
        {admin && data.technical?.llm && (
          <p className="footnote">
            Technical: {data.technical.llm.calls} model call{data.technical.llm.calls === 1 ? '' : 's'}, {data.technical.llm.tokens.total.toLocaleString('en-US')} tokens, {data.technical.llm.retries} retried · trace {data.technical.trace_source ?? 'unavailable'}
            {data.technical.classification_method ? ` · classification method ${data.technical.classification_method}` : ''}
          </p>
        )}
        <nav className="xp-nav" aria-label="Sections of this explanation">
          {sections.map(([key, text]) => (
            <a key={key} href={`#${id(key)}`}>
              {text}
            </a>
          ))}
        </nav>
      </Card>

      <Section id={id('generation')} title="How the brief was generated" lead="Eight stages run in order. Each is marked with what made the call: an AI model, fixed rules, search, statistical models or a person.">
        <Steps data={data} />
      </Section>

      <Section id={id('sources')} title="Where each statement came from" lead="Every finding and recommendation must name the sources behind it. Statements with no source are flagged rather than hidden.">
        <Lineage rows={data.lineage} onSource={onSource} />
      </Section>

      <Section id={id('ranking')} title="How comparable claims were found and ranked" lead="Exact filters choose the pool, then three ranked lists are combined. This shows each method’s share of every score.">
        <Retrieval data={data.retrieval} />
      </Section>

      <Section id={id('priority')} title="Why this handling priority" lead="A transparent point rule orders the queue. It ranks attention only; it never decides a claim.">
        <Priority data={data.priority} />
      </Section>

      <Section id={id('estimates')} title="What the model estimates rest on" lead="Three statistical models estimate the claim amount, resolution time and a dataset fraud-flag score. They describe associations in synthetic data, not causes.">
        {data.estimates.available ? (
          <>
            <div className="xp-ests">
              {data.estimates.tasks.map((task) => (
                <Estimate key={task.id} task={task} />
              ))}
            </div>
            {data.estimates.note && <p className="footnote">{data.estimates.note}</p>}
            {!!data.estimates.warnings?.length && <p className="footnote">Warnings: {data.estimates.warnings.join('; ')}</p>}
          </>
        ) : (
          <div className="small-empty">{data.estimates.reason}</div>
        )}
      </Section>

      <Section id={id('evaluation')} title="How the brief was evaluated" lead="Four layers look at the brief. Two are gates: mechanical validation and a person. The AI review and the evidence counts inform the handler but never decide.">
        <div className="xp-layers">
          {data.evaluation.layers.map((layer) => (
            <Layer key={layer.id} layer={layer} admin={admin} />
          ))}
        </div>
      </Section>

      <Section id={id('limits')} title="Boundaries and limitations">
        <div className="xp-limits">
          <div>
            <h4 className="mini-title">What this system will not do</h4>
            <ul className="plain-list">
              {data.boundaries.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="mini-title">What is not known for this brief</h4>
            {data.limitations.length ? (
              <ul className="plain-list">
                {data.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            ) : (
              <p className="footnote">No limitations were stated for this brief.</p>
            )}
          </div>
        </div>
        {timeline && (
          <details className="disclose">
            <summary>Time spent per stage · {formatDuration(timeline.total_ms)} in total{timeline.source === 'reconstructed' ? ' (approximate)' : ''}</summary>
            <div className="disclose-body">
              <div className="bars">
                {timeline.stages.map((s) => (
                  <div className="bar-row" key={s.stage}>
                    <span className="nm">{STAGES.find((x) => x.key === s.stage)?.name ?? label(s.stage)}</span>
                    <Bar value={s.duration_ms / longest} />
                    <span className="vl">{formatDuration(s.duration_ms)}</span>
                  </div>
                ))}
              </div>
              {timeline.source === 'reconstructed' && <p className="footnote">This brief was saved before timings were recorded; stage times are inferred from the audit log.</p>}
            </div>
          </details>
        )}
      </Section>
    </div>
  )
}

export function ExplanationView({ runId, admin = false, idPrefix, onOpenTrace, onSource }: { runId: string; admin?: boolean; idPrefix?: string; onOpenTrace?: (runId: string) => void; onSource?: (id: string) => void }) {
  const [data, setData] = useState<Explanation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  // Callers key this component by run ID, so a new run always starts from a clean state.
  useEffect(() => {
    const controller = new AbortController()
    api<Explanation>(`/api/investigations/${encodeURIComponent(runId)}/explanation`, { signal: controller.signal })
      .then((result) => {
        if (!Array.isArray(result.pipeline) || !result.retrieval) throw new Error('The explanation response was invalid.')
        if (!controller.signal.aborted) setData(result)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message)
      })
    return () => controller.abort()
  }, [runId, attempt])
  if (error)
    return (
      <div>
        <ErrorBox message={error} />
        <div className="case-tools">
          <button
            className="btn"
            type="button"
            onClick={() => {
              setError(null)
              setAttempt((n) => n + 1)
            }}
          >
            <RefreshCw size={14} /> Try again
          </button>
        </div>
      </div>
    )
  if (!data) return <div className="skeleton" style={{ height: 380 }} aria-busy="true" aria-label="Loading the explanation" />
  return <ExplanationBody data={data} admin={admin} idPrefix={idPrefix} onOpenTrace={onOpenTrace ? () => onOpenTrace(runId) : undefined} onSource={onSource} />
}
