import { Badge } from './StatusBadge.jsx'

/**
 * One AI citation, shown next to the verifier's verdict on it.
 *
 * The prompt asked the model to cite real evidence; a deterministic verifier then checked
 * whether each excerpt actually appears in the output of the command it names. That verdict
 * is what this component renders — a failed citation is displayed in full with its reason,
 * never hidden, because "the model quoted something that is not there" is exactly what a
 * reviewer most needs to see.
 */
export function EvidenceCitation({ citation, index, verdict }) {
  const failed = verdict?.state === 'failed'
  const verified = verdict?.state === 'verified'

  return (
    <article
      className={`rounded-md border p-3 ${
        failed
          ? 'border-rose-700/70 bg-rose-950/30'
          : 'border-slate-800 bg-slate-950/50'
      }`}
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-slate-500">#{index + 1}</span>
        <span className="font-mono text-xs text-sky-300">{citation.source_command}</span>
        <span className="ml-auto">
          {verified && <Badge tone="emerald">Verified in output</Badge>}
          {failed && <Badge tone="rose">Not found in output</Badge>}
          {!verified && !failed && <Badge>Unchecked</Badge>}
        </span>
      </header>

      <blockquote className="mt-2 border-l-2 border-slate-700 pl-3">
        <pre className="cisco-output overflow-x-auto">{citation.excerpt}</pre>
      </blockquote>

      <p className="mt-2 text-xs text-slate-400">
        <span className="font-semibold uppercase tracking-wider text-slate-500">
          Why it matters:{' '}
        </span>
        {citation.why_it_matters}
      </p>

      {failed && verdict.detail && (
        <p className="mt-2 border-t border-rose-900/60 pt-2 text-xs text-rose-200">
          <span className="font-semibold">Verifier ({verdict.reason}):</span> {verdict.detail}
        </p>
      )}
    </article>
  )
}

/**
 * Index the stored integrity record by citation position.
 *
 * `verified_items` and `failed_items` both carry the `index` of the citation they refer to,
 * so the pairing is exact rather than inferred from text matching.
 */
export function verdictsByIndex(integrity) {
  const map = new Map()
  for (const item of integrity?.verified_items || []) {
    map.set(item.index, { state: 'verified' })
  }
  for (const item of integrity?.failed_items || []) {
    map.set(item.index, { state: 'failed', reason: item.reason, detail: item.detail })
  }
  return map
}

export default EvidenceCitation
