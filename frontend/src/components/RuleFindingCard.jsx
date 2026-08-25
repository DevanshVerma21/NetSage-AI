import { Badge, SeverityBadge } from './StatusBadge.jsx'

/**
 * One deterministic finding.
 *
 * Styled to look mechanical rather than advisory: a rule either matched or it did not, and
 * `confidence` is the literal string "deterministic" for every finding the engine emits.
 * Nothing on this card came from a language model.
 */
export function RuleFindingCard({ finding }) {
  return (
    <article className="rounded-md border border-sky-900/60 bg-slate-950/50 p-3">
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-bold text-sky-300">{finding.rule_id}</span>
        <span className="text-sm font-semibold text-slate-100">{finding.rule_name}</span>
        <span className="ml-auto flex items-center gap-2">
          <Badge tone="rose">Fail</Badge>
          <SeverityBadge severity={finding.severity} />
        </span>
      </header>

      <p className="mt-2 text-sm text-slate-300">{finding.message}</p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge tone="violet">{finding.category}</Badge>
        <Badge>{finding.osi_layer}</Badge>
        {finding.affected?.length > 0 && (
          <span className="font-mono text-[11px] text-slate-400">
            {finding.affected.join(' · ')}
          </span>
        )}
      </div>

      {finding.evidence?.length > 0 && (
        <dl className="mt-3 space-y-1.5 border-t border-slate-800 pt-3">
          {finding.evidence.map((item, index) => (
            <div key={index} className="text-xs">
              <dt className="font-mono text-slate-500">{item.source}</dt>
              <dd className="text-slate-300">{item.detail}</dd>
            </div>
          ))}
        </dl>
      )}

      {finding.suggested_check && (
        <p className="mt-3 border-t border-slate-800 pt-3 text-xs text-slate-400">
          Confirm with{' '}
          <code className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-slate-200">
            {finding.suggested_check}
          </code>
        </p>
      )}
    </article>
  )
}

/**
 * A mandatory rule that ran and found nothing.
 *
 * Shown so the panel reports the whole check, not only the failures — an evaluator should
 * be able to see that all six mandatory rules executed against this case.
 */
export function RulePassRow({ ruleId }) {
  return (
    <div className="flex items-center gap-2 rounded border border-slate-800 bg-slate-900/30 px-3 py-1.5">
      <span className="font-mono text-xs text-slate-400">{ruleId}</span>
      <Badge tone="emerald" className="ml-auto">
        Pass
      </Badge>
    </div>
  )
}

export default RuleFindingCard
