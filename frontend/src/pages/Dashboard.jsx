/**
 * The dashboard. Every figure on this page is a field of `GET /api/dashboard`.
 *
 * The page performs no arithmetic on the payload — no rate, no percentage, no total is
 * derived here. That is deliberate: the backend recalculates each figure from the stored
 * cases, evaluation records and review records on every request, so a number shown here
 * cannot drift from the record it describes.
 *
 * The deterministic block and the AI-evaluation block are kept visually and structurally
 * apart, with their own denominators. The rule engine ran over every stored case; the model
 * has not. Merging them into one "accuracy" would be the single most misleading thing this
 * page could do.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getDashboard } from '../api/client.js'
import { Panel, Loading, ErrorNotice, Meta } from '../components/ui.jsx'
import { Badge } from '../components/StatusBadge.jsx'
import { Bar, CoverageBanner, EmptyState, SourceNote, Stat } from '../components/Metrics.jsx'

const pct = (rate) => `${Math.round(rate * 1000) / 10}%`

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    getDashboard()
      .then((payload) => live && setData(payload))
      .catch((err) => live && setError(err))
    return () => {
      live = false
    }
  }, [])

  if (error) return <ErrorNotice error={error} />
  if (!data) return <Loading label="Calculating metrics from stored records…" />

  const { deterministic: det, ai_evaluation: ai, human_review: hr } = data

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold text-slate-100">Dashboard</h1>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-400">
          {data.separation_note}
        </p>
      </header>

      <CoverageBanner ai={ai} />

      {/* ---- deterministic ---------------------------------------------------------- */}
      <Panel
        tone="deterministic"
        label="Deterministic"
        title="Rule engine"
        subtitle="Ran offline over every stored case. No model, no provider, no network call."
        right={
          <Badge tone={det.golden_case_result === 'PASS' ? 'emerald' : 'rose'}>
            golden test: {det.golden_case_result}
          </Badge>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Total cases" value={det.total_cases} tone="deterministic" />
          <Stat
            label="Total rules"
            value={det.total_rules}
            tone="deterministic"
            hint={`${det.mandatory_rules} mandatory · ${det.optional_rules} optional`}
          />
          <Stat
            label="Rule pass rate"
            value={pct(det.rule_pass_rate)}
            tone={det.rule_pass_rate === 1 ? 'good' : 'warn'}
            hint="Cases whose fired rule ids equal their expected rule ids"
          />
          <Stat
            label="Expected vs fired"
            value={det.cases_matching_expected_rules}
            of={det.total_cases}
            tone={det.cases_not_matching === 0 ? 'good' : 'danger'}
            hint={`${det.cases_not_matching} disagree`}
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="space-y-2.5">
            <Bar
              label="Cases matching expected rules"
              value={det.cases_matching_expected_rules}
              total={det.total_cases}
              tone="sky"
            />
            <Bar
              label="Mandatory rules of all rules"
              value={det.mandatory_rules}
              total={det.total_rules}
              tone="slate"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Meta label="Mandatory rule ids">
              <p className="font-mono text-xs leading-relaxed text-sky-200">
                {det.mandatory_rule_ids.join(' · ')}
              </p>
            </Meta>
            <Meta label="Optional rule ids">
              <p className="font-mono text-xs leading-relaxed text-slate-300">
                {det.optional_rule_ids.join(' · ')}
              </p>
            </Meta>
          </div>
        </div>

        {det.mismatches.length > 0 && (
          <ul className="mt-4 space-y-2">
            {det.mismatches.map((m) => (
              <li
                key={m.case_id}
                className="rounded-md border border-rose-900/60 bg-rose-950/25 px-3 py-2 text-xs"
              >
                <p className="font-mono font-semibold text-rose-200">{m.case_id}</p>
                <p className="mt-0.5 font-mono text-slate-300">
                  expected [{m.expected.join(', ')}] · fired [{m.fired.join(', ')}]
                </p>
              </li>
            ))}
          </ul>
        )}

        <SourceNote>
          DETERMINISTIC — {det.golden_case_detail} The expected-vs-fired comparison is re-run
          live against the {det.verified_against} when this page loads, not read from a test
          log. Cases are simulated lab topologies.
        </SourceNote>
      </Panel>

      {/* ---- AI evaluation ---------------------------------------------------------- */}
      <Panel
        tone="ai"
        label="AI evaluation"
        title="Stored model results"
        subtitle="Derived only from evaluation records that actually exist."
        right={<Badge tone={ai.coverage_complete ? 'emerald' : 'amber'}>{ai.status}</Badge>}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Cases evaluated"
            value={ai.evaluated}
            of={ai.total}
            tone={ai.evaluated === 0 ? 'danger' : 'ai'}
          />
          <Stat label="Pending evaluation" value={ai.pending} tone="warn" />
          <Stat
            label="Accuracy"
            value={ai.accuracy === null ? 'withheld' : pct(ai.accuracy.correct_rate)}
            tone={ai.accuracy === null ? 'muted' : 'ai'}
            hint={ai.accuracy === null ? 'Coverage incomplete' : 'Over all evaluated cases'}
          />
          <Stat
            label="Evidence integrity"
            value={
              ai.evaluated === 0
                ? 'no data'
                : `${ai.evidence.verified_citations}/${ai.evidence.total_citations}`
            }
            tone={ai.evaluated === 0 ? 'muted' : 'ai'}
            hint={ai.evaluated === 0 ? 'No official evaluation stored' : 'Citations verified'}
          />
        </div>

        {ai.evaluated === 0 ? (
          <div className="mt-4">
            <EmptyState title="No official AI evaluation is stored">
              <p>{ai.headline}</p>
              <p className="mt-2">
                Nothing on this page substitutes for the missing results: accuracy is withheld
                rather than estimated, and the {ai.total} unevaluated cases are counted as
                unevaluated, not as passes.
              </p>
            </EmptyState>
          </div>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div className="space-y-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
                Result — out of {ai.evaluated} evaluated
              </p>
              <Bar label="CORRECT" value={ai.results.CORRECT} total={ai.evaluated} tone="emerald" />
              <Bar label="PARTIAL" value={ai.results.PARTIAL} total={ai.evaluated} tone="amber" />
              <Bar label="INCORRECT" value={ai.results.INCORRECT} total={ai.evaluated} tone="rose" />
            </div>
            <div className="space-y-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
                Evidence verification
              </p>
              <Bar
                label="Verified citations"
                value={ai.evidence.verified_citations}
                total={ai.evidence.total_citations}
                tone="violet"
              />
              <Bar
                label="Integrity passed"
                value={ai.evidence.integrity.passed}
                total={ai.evaluated}
                tone="emerald"
              />
              <Bar
                label="Confidence capped by the checks"
                value={ai.confidence.capped}
                total={ai.evaluated}
                tone="amber"
              />
            </div>
          </div>
        )}

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Stat
            label="Stored attempts"
            value={ai.stored_records}
            tone="muted"
            hint="Includes failed and invalidated rows, kept for audit"
          />
          <Stat
            label="Failed provider calls"
            value={ai.failed_calls}
            tone={ai.failed_calls ? 'warn' : 'muted'}
            hint={ai.failed_case_ids.join(', ') || 'none'}
          />
          <Stat
            label="Invalidated records"
            value={ai.invalidated}
            tone={ai.invalidated ? 'warn' : 'muted'}
            hint={ai.invalidated_case_ids.join(', ') || 'none'}
          />
        </div>

        <SourceNote>
          AI EVALUATION — {ai.accuracy_note} An invalidated record counts as not evaluated: it
          stays in the results file for auditability but never enters an official figure.
        </SourceNote>
      </Panel>

      {/* ---- human review ----------------------------------------------------------- */}
      <Panel
        label="Human gate"
        title="Human review"
        subtitle="Verdicts recorded server-side. Approval never lives in the browser."
        tone={hr.corrections_complete ? 'default' : 'warn'}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Reviews recorded" value={hr.total_reviews} />
          <Stat label="Accepted" value={hr.accepted} tone="good" />
          <Stat label="Edited" value={hr.edited} tone="warn" />
          <Stat label="Rejected" value={hr.rejected} tone="danger" />
        </div>

        <div className="mt-4">
          <Bar
            label={`Genuine corrections (required for the Responsible AI log)`}
            value={hr.corrections}
            total={hr.required_corrections}
            tone="amber"
          />
        </div>

        {hr.incomplete_message && (
          <p className="mt-3 rounded-md border border-amber-700/70 bg-amber-950/25 px-3 py-2 text-sm font-semibold text-amber-200">
            {hr.incomplete_message}
          </p>
        )}

        <SourceNote>
          Counted from stored review records. No correction was invented to close the gap —{' '}
          <Link className="text-sky-300 underline decoration-dotted" to="/responsible-ai">
            see the Responsible AI page
          </Link>{' '}
          for the correction log and the known limitations.
        </SourceNote>
      </Panel>
    </div>
  )
}
