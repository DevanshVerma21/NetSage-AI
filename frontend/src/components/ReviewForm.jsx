import { useMemo, useState } from 'react'
import { Button, ErrorNotice, Field, inputClass } from './ui.jsx'

/**
 * The human verdict form.
 *
 * The three verdicts carry different burdens and the backend enforces them, so this form
 * mirrors those rules rather than inventing its own: an edit needs a reason code and at
 * least one actual correction, a rejection needs a reason code and notes. The mirroring is
 * a courtesy to the reviewer — the server is still the authority, and a server rejection is
 * surfaced verbatim rather than assumed impossible.
 *
 * Nothing here can describe a fix. A reviewer may narrow which deterministic findings the
 * simulator acts on, but the mutations themselves come from those findings.
 */

const REASON_CODES = [
  'wrong_root_cause',
  'incomplete_root_cause',
  'wrong_osi_layer',
  'wrong_category',
  'unverified_evidence',
  'insufficient_evidence',
  'conflicts_with_rules',
  'fix_steps_incorrect',
  'fix_steps_incomplete',
  'out_of_scope',
  'other',
]

const OSI_LAYERS = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7']
const CATEGORIES = [
  'VLAN',
  'GATEWAY',
  'DHCP',
  'DNS',
  'ROUTING',
  'ACL',
  'NAT',
  'WIRELESS',
  'INTERFACE_CONFIG',
]

export function ReviewForm({ diagnosis, verdict, onCancel, onSubmit, busy = false, error }) {
  const [reviewer, setReviewer] = useState('')
  const [reasonCode, setReasonCode] = useState('')
  const [notes, setNotes] = useState('')
  const [rootCause, setRootCause] = useState('')
  const [osiLayer, setOsiLayer] = useState('')
  const [category, setCategory] = useState('')
  const [fixSteps, setFixSteps] = useState('')
  const [ruleIds, setRuleIds] = useState([])

  const availableRuleIds = useMemo(
    () => [...new Set((diagnosis?.rule_findings || []).map((f) => f.rule_id))].sort(),
    [diagnosis],
  )

  const isEdit = verdict === 'edited'
  const isReject = verdict === 'rejected'

  const corrections = [rootCause, osiLayer, category, fixSteps.trim()].filter(Boolean)
  const blocked =
    (isEdit && (!reasonCode || corrections.length === 0)) ||
    (isReject && (!reasonCode || !notes.trim()))

  function handleSubmit(event) {
    event.preventDefault()
    if (blocked) return
    onSubmit({
      diagnosis_id: diagnosis.diagnosis_id,
      verdict,
      reviewer: reviewer.trim() || 'human-reviewer',
      reason_code: reasonCode || undefined,
      notes: notes.trim() || undefined,
      corrected_root_cause: isEdit && rootCause.trim() ? rootCause.trim() : undefined,
      corrected_osi_layer: isEdit && osiLayer ? osiLayer : undefined,
      corrected_category: isEdit && category ? category : undefined,
      corrected_rule_ids: isEdit && ruleIds.length > 0 ? ruleIds : undefined,
      corrected_fix_steps: isEdit
        ? fixSteps
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean)
        : undefined,
    })
  }

  function toggleRule(ruleId) {
    setRuleIds((current) =>
      current.includes(ruleId)
        ? current.filter((id) => id !== ruleId)
        : [...current, ruleId],
    )
  }

  const headings = {
    accepted: 'Accept this diagnosis',
    edited: 'Edit and accept with corrections',
    rejected: 'Reject this diagnosis',
  }

  const blurbs = {
    accepted:
      'You agree with the root cause, OSI layer and category. The simulated fix will be derived from the deterministic findings.',
    edited:
      'Record what the AI got wrong. A reason code and at least one correction are required — an edit that records no correction is not a review.',
    rejected:
      'A reason code and notes are both required. A rejection is the most useful record in the Responsible-AI log, and a bare "rejected" teaches nobody anything. No fix can be applied afterwards.',
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-100">{headings[verdict]}</h3>
        <p className="mt-1 text-xs text-slate-400">{blurbs[verdict]}</p>
      </div>

      <Field label="Reviewer name" hint="Recorded in the audit trail.">
        <input
          className={inputClass}
          value={reviewer}
          onChange={(event) => setReviewer(event.target.value)}
          placeholder="human-reviewer"
        />
      </Field>

      {(isEdit || isReject) && (
        <Field label="Reason code" required>
          <select
            className={inputClass}
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value)}
          >
            <option value="">Select a reason code…</option>
            {REASON_CODES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </Field>
      )}

      {!isEdit && !isReject && (
        <Field label="Reason code" hint="Optional for an accepted review.">
          <select
            className={inputClass}
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value)}
          >
            <option value="">None</option>
            {REASON_CODES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </Field>
      )}

      <Field
        label="Notes"
        required={isReject}
        hint={isReject ? 'Explain why the diagnosis is wrong.' : 'Optional context.'}
      >
        <textarea
          className={`${inputClass} min-h-20`}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </Field>

      {isEdit && (
        <fieldset className="space-y-4 rounded-md border border-amber-800/60 bg-amber-950/15 p-3">
          <legend className="px-1 text-xs font-semibold uppercase tracking-wider text-amber-300">
            Corrections — at least one required
          </legend>

          <Field label="Corrected root cause" hint="Leave blank to keep the AI's wording.">
            <textarea
              className={`${inputClass} min-h-20`}
              value={rootCause}
              onChange={(event) => setRootCause(event.target.value)}
              placeholder={diagnosis?.ai?.root_cause}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={`Corrected OSI layer (AI said ${diagnosis?.ai?.osi_layer})`}>
              <select
                className={inputClass}
                value={osiLayer}
                onChange={(event) => setOsiLayer(event.target.value)}
              >
                <option value="">Unchanged</option>
                {OSI_LAYERS.map((layer) => (
                  <option key={layer} value={layer}>
                    {layer}
                  </option>
                ))}
              </select>
            </Field>

            <Field label={`Corrected category (AI said ${diagnosis?.ai?.category})`}>
              <select
                className={inputClass}
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <option value="">Unchanged</option>
                {CATEGORIES.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Corrected fix steps" hint="One step per line.">
            <textarea
              className={`${inputClass} min-h-24 font-mono text-xs`}
              value={fixSteps}
              onChange={(event) => setFixSteps(event.target.value)}
              placeholder={'SW1: vlan 30\nSW1: interface Vlan30 / no shutdown'}
            />
          </Field>

          {availableRuleIds.length > 0 && (
            <Field
              label="Narrow the simulated fix"
              hint="Optional. Unticked means every deterministic finding is addressed. You can only
                    narrow to findings the engine actually reported — you cannot invent one."
            >
              <div className="flex flex-wrap gap-2">
                {availableRuleIds.map((ruleId) => (
                  <label
                    key={ruleId}
                    className={`cursor-pointer rounded border px-2.5 py-1 font-mono text-xs ${
                      ruleIds.includes(ruleId)
                        ? 'border-amber-500 bg-amber-900/40 text-amber-100'
                        : 'border-slate-700 bg-slate-900 text-slate-400'
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={ruleIds.includes(ruleId)}
                      onChange={() => toggleRule(ruleId)}
                    />
                    {ruleId}
                  </label>
                ))}
              </div>
            </Field>
          )}
        </fieldset>
      )}

      <ErrorNotice error={error} />

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          busy={busy}
          disabled={blocked}
          variant={isReject ? 'reject' : isEdit ? 'edit' : 'accept'}
        >
          {isReject ? 'Submit rejection' : isEdit ? 'Submit corrections' : 'Submit acceptance'}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
        {blocked && (
          <p className="text-xs text-amber-300">
            {isReject
              ? 'A reason code and notes are required.'
              : 'A reason code and at least one correction are required.'}
          </p>
        )}
      </div>
    </form>
  )
}

export default ReviewForm
