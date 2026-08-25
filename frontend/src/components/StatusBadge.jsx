/**
 * Status vocabulary, in one place.
 *
 * The wording is the architecture stated out loud, so it is deliberately not paraphrased
 * per page: an unreviewed proposal always reads "Proposed — awaiting human review", an
 * accepted or edited one "Human reviewed", and a rejected one "Rejected — fix unavailable".
 * The AI is never described as having done anything to the network.
 */

const TONES = {
  slate: 'border-slate-700 bg-slate-800/70 text-slate-300',
  amber: 'border-amber-600/70 bg-amber-950/50 text-amber-200',
  emerald: 'border-emerald-600/70 bg-emerald-950/50 text-emerald-200',
  rose: 'border-rose-700/70 bg-rose-950/50 text-rose-200',
  sky: 'border-sky-600/70 bg-sky-950/50 text-sky-200',
  violet: 'border-violet-600/70 bg-violet-950/50 text-violet-200',
}

export function Badge({ tone = 'slate', children, className = '' }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
        TONES[tone] || TONES.slate
      } ${className}`}
    >
      {children}
    </span>
  )
}

const DIAGNOSIS_STATUS = {
  awaiting_human_review: { tone: 'amber', text: 'Proposed — awaiting human review' },
  accepted: { tone: 'emerald', text: 'Human reviewed' },
  edited: { tone: 'emerald', text: 'Human reviewed' },
  rejected: { tone: 'rose', text: 'Rejected — fix unavailable' },
}

/** The review state of a diagnosis record. Drives nothing but the label — the gate is
 *  enforced by the backend, which is why this component only ever reads `status`. */
export function StatusBadge({ status, applied = false, className = '' }) {
  const entry = DIAGNOSIS_STATUS[status] || { tone: 'slate', text: status || 'unknown' }
  return (
    <span className={`inline-flex flex-wrap items-center gap-2 ${className}`}>
      <Badge tone={entry.tone}>{entry.text}</Badge>
      {applied && <Badge tone="sky">Simulated fix applied</Badge>}
    </span>
  )
}

const SEVERITY_TONE = {
  Critical: 'rose',
  High: 'rose',
  Medium: 'amber',
  Low: 'slate',
}

export function SeverityBadge({ severity }) {
  return <Badge tone={SEVERITY_TONE[severity] || 'slate'}>{severity}</Badge>
}

export function VerdictBadge({ verdict }) {
  const tone = verdict === 'rejected' ? 'rose' : verdict === 'edited' ? 'amber' : 'emerald'
  return <Badge tone={tone}>{verdict}</Badge>
}

const VERIFICATION = {
  verified: { tone: 'emerald', text: 'Verification passed' },
  partial: { tone: 'amber', text: 'Partially verified' },
  failed: { tone: 'rose', text: 'Verification failed' },
}

export function VerificationBadge({ result }) {
  const entry = VERIFICATION[result] || { tone: 'slate', text: result }
  return <Badge tone={entry.tone}>{entry.text}</Badge>
}
