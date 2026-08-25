import { Badge } from './StatusBadge.jsx'
import { ConfidenceBadge } from './ConfidenceBadge.jsx'
import { EvidenceCitation, verdictsByIndex } from './EvidenceCitation.jsx'

/**
 * The AI's proposal, rendered as a proposal.
 *
 * Everything here is what a model suggested. The two independent checks that ran over it —
 * evidence verification and reconciliation against the deterministic engine — are shown
 * before the diagnosis itself when either of them is unhappy, so a reviewer meets the
 * caveat before the conclusion rather than after it. Fix steps are labelled as commands a
 * human would type; nothing on this card was executed anywhere.
 */

const RECONCILIATION_COPY = {
  agree: {
    tone: 'emerald',
    text: 'Agrees with the deterministic engine',
  },
  partial: {
    tone: 'amber',
    text: 'Partially agrees with the deterministic engine',
  },
  ai_only: {
    tone: 'amber',
    text: 'AI only — no deterministic rule corroborates this',
  },
  rules_only: {
    tone: 'amber',
    text: 'Rules only — the AI missed what the engine found',
  },
  conflict: {
    tone: 'rose',
    text: 'Conflicts with the deterministic engine',
  },
}

function Warning({ tone = 'warn', title, children }) {
  const styles =
    tone === 'danger'
      ? 'border-rose-700 bg-rose-950/50 text-rose-100'
      : 'border-amber-600/80 bg-amber-950/40 text-amber-100'
  return (
    <div role="alert" className={`rounded-md border-2 px-4 py-3 ${styles}`}>
      <p className="text-sm font-bold uppercase tracking-wide">{title}</p>
      <p className="mt-1 text-sm opacity-90">{children}</p>
    </div>
  )
}

export function AIDiagnosisCard({ diagnosis }) {
  const ai = diagnosis.ai
  const integrity = diagnosis.evidence_integrity
  const reconciliation = diagnosis.reconciliation
  const verdicts = verdictsByIndex(integrity)
  const reconCopy = RECONCILIATION_COPY[reconciliation?.status] || {
    tone: 'slate',
    text: reconciliation?.status,
  }

  return (
    <div className="space-y-4">
      {/* --- the independent checks, before the conclusion ------------------------------ */}

      {integrity?.status === 'failed' && (
        <Warning tone="danger" title="Evidence verification failed">
          {integrity.failed_count} of {integrity.failed_count + integrity.verified_count}{' '}
          citations could not be located in the supplied show output. Confidence has been
          capped at LOW. Treat this diagnosis as unsubstantiated until you have checked the
          failed citations below yourself.
        </Warning>
      )}

      {integrity?.status === 'partial' && (
        <Warning title="Some evidence could not be verified">
          {integrity.verified_count} citation(s) were located in the supplied output and{' '}
          {integrity.failed_count} could not be. The unverified ones are shown in full below.
        </Warning>
      )}

      {reconciliation?.status === 'conflict' && (
        <Warning tone="danger" title="Conflicts with the deterministic rule engine">
          {reconciliation.reason ||
            'The AI named a cause the rule engine contradicts. The deterministic findings are the more reliable of the two.'}
        </Warning>
      )}

      {ai.insufficient_evidence && (
        <Warning title="The model declined to commit">
          It reported the supplied evidence as insufficient. Run the recommended next command
          and diagnose again rather than acting on this proposal.
        </Warning>
      )}

      {diagnosis.warnings?.length > 0 && (
        <Warning title="Pipeline warnings">
          <span className="block space-y-1">
            {diagnosis.warnings.map((warning, index) => (
              <span key={index} className="block">
                • {warning}
              </span>
            ))}
          </span>
        </Warning>
      )}

      {/* --- root cause ---------------------------------------------------------------- */}

      <div className="rounded-md border border-violet-900/60 bg-slate-950/40 p-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-400">
          Proposed root cause
        </p>
        <p className="mt-2 text-[15px] leading-relaxed text-slate-100">{ai.root_cause}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge tone="violet">{ai.category}</Badge>
          <Badge>{ai.osi_layer}</Badge>
          <Badge tone={reconCopy.tone}>{reconCopy.text}</Badge>
        </div>
        {reconciliation?.reason && reconciliation.status !== 'conflict' && (
          <p className="mt-2 text-xs text-slate-400">{reconciliation.reason}</p>
        )}
      </div>

      <ConfidenceBadge confidence={diagnosis.confidence} />

      {/* --- evidence ------------------------------------------------------------------ */}

      <section>
        <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Evidence citations
          <span className="font-normal normal-case text-slate-500">
            ({integrity?.verified_count ?? 0} verified · {integrity?.failed_count ?? 0} failed)
          </span>
        </h3>
        {ai.evidence?.length > 0 ? (
          <div className="space-y-2">
            {ai.evidence.map((citation, index) => (
              <EvidenceCitation
                key={index}
                citation={citation}
                index={index}
                verdict={verdicts.get(index)}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            The model cited nothing, having reported the evidence as insufficient.
          </p>
        )}
      </section>

      {/* --- next command -------------------------------------------------------------- */}

      <section className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
          Recommended next command
        </p>
        <code className="mt-1.5 block font-mono text-sm text-emerald-200">
          {ai.next_command}
        </code>
      </section>

      {/* --- fix steps ----------------------------------------------------------------- */}

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Proposed fix steps
          <span className="ml-2 font-normal normal-case text-slate-500">
            — commands a human would type. Nothing here has been run.
          </span>
        </h3>
        {ai.fix_steps?.length > 0 ? (
          <ol className="space-y-2">
            {ai.fix_steps.map((step) => (
              <li
                key={step.order}
                className="rounded-md border border-slate-800 bg-slate-950/50 p-3"
              >
                <header className="flex flex-wrap items-center gap-2">
                  <span className="flex size-5 items-center justify-center rounded-full bg-slate-800 text-[11px] font-bold text-slate-300">
                    {step.order}
                  </span>
                  <span className="font-mono text-xs font-semibold text-sky-300">
                    {step.device}
                  </span>
                  <Badge
                    tone={step.risk === 'high' ? 'rose' : step.risk === 'medium' ? 'amber' : 'slate'}
                    className="ml-auto"
                  >
                    {step.risk} risk
                  </Badge>
                </header>
                <pre className="cisco-output mt-2 overflow-x-auto">
                  {step.cli_commands.join('\n')}
                </pre>
                <p className="mt-2 text-xs text-slate-400">{step.rationale}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-slate-500">
            No fix steps were proposed — the model declined to guess.
          </p>
        )}
      </section>

      {/* --- verification steps -------------------------------------------------------- */}

      {ai.verification_steps?.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Suggested verification
          </h3>
          <ul className="space-y-1.5">
            {ai.verification_steps.map((step, index) => (
              <li
                key={index}
                className="rounded border border-slate-800 bg-slate-950/50 px-3 py-2 text-xs"
              >
                <code className="font-mono text-emerald-200">{step.command}</code>
                <p className="mt-1 text-slate-400">Expect: {step.expected_result}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --- alternatives and reviewer notes ------------------------------------------- */}

      {ai.alternative_hypotheses?.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            Alternatives considered
          </h3>
          <ul className="space-y-1.5 text-xs">
            {ai.alternative_hypotheses.map((item, index) => (
              <li key={index} className="rounded border border-slate-800 px-3 py-2">
                <p className="text-slate-200">{item.cause}</p>
                <p className="mt-0.5 text-slate-500">Less likely: {item.why_less_likely}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ai.notes_for_reviewer && (
        <section className="rounded-md border border-slate-800 bg-slate-900/40 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
            Notes for the reviewer
          </p>
          <p className="mt-1 text-xs text-slate-300">{ai.notes_for_reviewer}</p>
        </section>
      )}

      {/* --- provenance ---------------------------------------------------------------- */}

      <footer className="flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-800 pt-3 font-mono text-[11px] text-slate-500">
        <span>{diagnosis.diagnosis_id}</span>
        <span>provider: {diagnosis.provider}</span>
        <span>model: {diagnosis.model}</span>
        <span>
          prompt: {diagnosis.prompt_name} v{diagnosis.prompt_version}
        </span>
        <span>sha256: {diagnosis.prompt_sha256?.slice(0, 12)}…</span>
        <span>{diagnosis.latency_ms} ms</span>
      </footer>
    </div>
  )
}

export default AIDiagnosisCard
