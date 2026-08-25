import { Badge } from './StatusBadge.jsx'

/**
 * The model's confidence and the system's, shown side by side.
 *
 * Never one number. The backend stores `model_confidence` and `effective_confidence`
 * separately precisely so a reviewer can see the gap between what the model claimed and
 * what survived independent checking, and collapsing them here would throw away the whole
 * point of the capping table. When they differ, the reasons are listed verbatim.
 */

const TONE = { high: 'emerald', medium: 'amber', low: 'rose' }

function pct(score) {
  return typeof score === 'number' ? `${Math.round(score * 100)}%` : '—'
}

export function ConfidenceBadge({ confidence }) {
  if (!confidence) return null
  const {
    model_confidence: model,
    effective_confidence: effective,
    model_confidence_score: modelScore,
    effective_confidence_score: effectiveScore,
    was_capped: capped,
    cap_reasons: reasons = [],
    summary,
  } = confidence

  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
            AI claimed
          </p>
          <div className="mt-1 flex items-center gap-2">
            <Badge tone={TONE[model] || 'slate'}>{model}</Badge>
            <span className="font-mono text-xs text-slate-400">{pct(modelScore)}</span>
          </div>
        </div>

        <div aria-hidden className="text-slate-600">
          →
        </div>

        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
            Effective (after checks)
          </p>
          <div className="mt-1 flex items-center gap-2">
            <Badge tone={TONE[effective] || 'slate'}>{effective}</Badge>
            <span className="font-mono text-xs text-slate-400">{pct(effectiveScore)}</span>
          </div>
        </div>

        {capped && <Badge tone="amber">Capped by verification</Badge>}
      </div>

      {capped && reasons.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-slate-800 pt-3 text-xs text-amber-200/90">
          {reasons.map((reason, index) => (
            <li key={index}>• {reason}</li>
          ))}
        </ul>
      )}

      {!capped && summary && <p className="mt-2 text-xs text-slate-500">{summary}</p>}
    </div>
  )
}

export default ConfidenceBadge
