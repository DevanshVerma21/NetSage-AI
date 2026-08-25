import { Badge, VerificationBadge } from './StatusBadge.jsx'
import { RuleFindingCard } from './RuleFindingCard.jsx'

/**
 * The result of a simulated fix.
 *
 * The verification is not the AI's opinion of its own work: the deterministic engine was
 * re-run over the mutated copy of the lab model, and this is the before/after diff. A fix
 * that resolves its target but introduces a new finding is never reported as verified, which
 * is why `new_rule_ids` is given the same prominence as `resolved_rule_ids`.
 *
 * `disclaimer` and `execution_scope` are rendered straight from the stored record rather
 * than written into this component, so the UI cannot claim a scope the backend did not.
 */

function Count({ label, ids = [], tone }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold text-slate-100">{ids.length}</p>
      {ids.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {ids.map((id) => (
            <Badge key={id} tone={tone}>
              {id}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

export function FixVerificationCard({ run }) {
  const verified = run.verification_result === 'verified'

  return (
    <div className="space-y-4">
      {/* --- the headline verdict ------------------------------------------------------- */}
      <div
        className={`rounded-md border-2 px-4 py-3 ${
          verified
            ? 'border-emerald-600 bg-emerald-950/40'
            : run.verification_result === 'partial'
              ? 'border-amber-600 bg-amber-950/40'
              : 'border-rose-700 bg-rose-950/40'
        }`}
      >
        <p
          className={`text-base font-bold uppercase tracking-wide ${
            verified
              ? 'text-emerald-200'
              : run.verification_result === 'partial'
                ? 'text-amber-200'
                : 'text-rose-200'
          }`}
        >
          {verified
            ? 'Verification passed'
            : run.verification_result === 'partial'
              ? 'Partially verified'
              : 'Verification failed'}
        </p>
        {run.verification_summary && (
          <p className="mt-1 whitespace-pre-line text-sm text-slate-200/90">
            {run.verification_summary}
          </p>
        )}
      </div>

      {/* --- scope, verbatim from the record ------------------------------------------- */}
      <div className="rounded-md border border-sky-800/70 bg-sky-950/30 px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-sky-400">
          Execution scope: {run.execution_scope}
        </p>
        <p className="mt-1 text-sm text-sky-100">{run.disclaimer}</p>
      </div>

      {/* --- the diff ------------------------------------------------------------------ */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Count label="Resolved" ids={run.resolved_rule_ids} tone="emerald" />
        <Count label="Newly introduced" ids={run.new_rule_ids} tone="rose" />
        <Count label="Still firing" ids={run.remaining_rule_ids} tone="amber" />
      </div>

      {/* --- what the simulator did to its copy --------------------------------------- */}
      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Mutations applied to the copied lab model
        </h3>
        <ul className="space-y-1.5">
          {run.mutations.map((mutation, index) => (
            <li
              key={index}
              className={`flex flex-wrap items-baseline gap-2 rounded border px-3 py-2 text-xs ${
                mutation.applied
                  ? 'border-slate-800 bg-slate-950/50'
                  : 'border-amber-800/60 bg-amber-950/20'
              }`}
            >
              <Badge tone={mutation.applied ? 'emerald' : 'amber'}>
                {mutation.applied ? 'applied' : 'skipped'}
              </Badge>
              <code className="font-mono text-slate-200">{mutation.type}</code>
              {mutation.rule_id && (
                <span className="font-mono text-slate-500">[{mutation.rule_id}]</span>
              )}
              <span className="text-slate-400">
                {mutation.detail || mutation.skipped_reason}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* --- before / after ----------------------------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Findings before
            <Badge tone="rose">{run.findings_before.length}</Badge>
          </h3>
          <div className="space-y-2">
            {run.findings_before.map((finding, index) => (
              <RuleFindingCard key={index} finding={finding} />
            ))}
          </div>
        </section>

        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Findings after
            <Badge tone={run.findings_after.length === 0 ? 'emerald' : 'amber'}>
              {run.findings_after.length}
            </Badge>
          </h3>
          {run.findings_after.length === 0 ? (
            <p className="rounded-md border border-emerald-800/60 bg-emerald-950/25 px-3 py-4 text-sm text-emerald-200">
              The deterministic engine reports no findings against the mutated lab model.
            </p>
          ) : (
            <div className="space-y-2">
              {run.findings_after.map((finding, index) => (
                <RuleFindingCard key={index} finding={finding} />
              ))}
            </div>
          )}
        </section>
      </div>

      <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-800 pt-3 font-mono text-[11px] text-slate-500">
        <span>{run.run_id}</span>
        <span>review: {run.review_id}</span>
        <span>diagnosis: {run.diagnosis_id}</span>
        <span>verdict: {run.verdict}</span>
        <VerificationBadge result={run.verification_result} />
      </footer>
    </div>
  )
}

export default FixVerificationCard
