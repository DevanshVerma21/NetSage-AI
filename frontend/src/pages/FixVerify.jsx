import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { applyFix, getDiagnosis, getFixes, getReview } from '../api/client.js'
import { FixVerificationCard } from '../components/FixVerificationCard.jsx'
import { Badge, StatusBadge, VerdictBadge } from '../components/StatusBadge.jsx'
import { Button, ErrorNotice, Loading, Meta, Panel } from '../components/ui.jsx'

/**
 * Fix & Verify.
 *
 * This page is reachable only with a review id, and the apply control is rendered only when
 * the stored verdict permits a fix — but that is presentation, not enforcement. The backend
 * refuses an unreviewed or rejected diagnosis with HTTP 409 from its own records, so hiding
 * the button is a courtesy and the 409 is the guarantee. Both are shown honestly here.
 *
 * The recommended fix is not something this page composes: the mutations come from the
 * reviewed diagnosis's deterministic findings, and the request carries only a review id.
 */
export function FixVerify() {
  const { reviewId } = useParams()

  const [review, setReview] = useState(null)
  const [diagnosis, setDiagnosis] = useState(null)
  const [run, setRun] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [loading, setLoading] = useState(true)

  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    ;(async () => {
      try {
        const reviewRecord = await getReview(reviewId)
        if (!active) return
        setReview(reviewRecord)

        const diagnosisRecord = await getDiagnosis(reviewRecord.diagnosis_id)
        if (!active) return
        setDiagnosis(diagnosisRecord)

        // A fix already simulated for this review is shown rather than re-run: a second
        // apply is a 409, and the stored result is the one that matters. The server filters
        // by review_id, so at most one run can come back.
        const runs = await getFixes({ review_id: reviewRecord.review_id })
        if (!active) return
        if (runs.length > 0) setRun(runs[0])
      } catch (error) {
        if (active) setLoadError(error)
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [reviewId])

  async function apply() {
    setApplying(true)
    setApplyError(null)
    try {
      const result = await applyFix(reviewId)
      setRun(result)
      setDiagnosis(await getDiagnosis(result.diagnosis_id))
    } catch (error) {
      setApplyError(error)
    } finally {
      setApplying(false)
    }
  }

  if (loading) return <Loading label="Loading the approved diagnosis…" />
  if (loadError) {
    return (
      <div className="space-y-4">
        <ErrorNotice error={loadError} />
        <Link to="/cases" className="text-sm text-sky-400 hover:underline">
          ← Back to the case library
        </Link>
      </div>
    )
  }
  if (!review || !diagnosis) return null

  const permitted = review.verdict === 'accepted' || review.verdict === 'edited'
  const targetedRuleIds =
    review.corrected_rule_ids?.length > 0 ? review.corrected_rule_ids : diagnosis.rule_ids
  const fixSteps =
    review.corrected_fix_steps?.length > 0
      ? review.corrected_fix_steps
      : diagnosis.ai.fix_steps.map(
          (step) => `${step.device}: ${step.cli_commands.join(' / ')}`,
        )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to={`/cases/${diagnosis.case_id}`}
            className="text-xs text-sky-400 hover:underline"
          >
            ← {diagnosis.case_id} Triage Workbench
          </Link>
          <h2 className="mt-1 text-xl font-semibold text-slate-50">Fix &amp; Verify</h2>
          <p className="mt-1 font-mono text-xs text-slate-500">{review.review_id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={diagnosis.status} applied={diagnosis.applied} />
          <Badge tone="sky">Simulation only</Badge>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* --- what was approved, and by whom ----------------------------------------- */}
        <Panel label="Human decision" title="The verdict this fix rests on">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <VerdictBadge verdict={review.verdict} />
              <span className="text-sm text-slate-300">{review.reviewer}</span>
              <span className="font-mono text-xs text-slate-500">{review.created_at}</span>
            </div>
            {review.reason_code && <Meta label="Reason code">{review.reason_code}</Meta>}
            {review.notes && <Meta label="Notes">{review.notes}</Meta>}

            <Meta label="Agreement with the AI">
              <div className="flex flex-wrap gap-2">
                {Object.entries(review.agreement).map(([field, agreed]) => (
                  <Badge key={field} tone={agreed ? 'emerald' : 'rose'}>
                    {field}: {agreed ? 'agreed' : 'disagreed'}
                  </Badge>
                ))}
              </div>
            </Meta>

            {review.corrected_root_cause && (
              <Meta label="Reviewer's corrected root cause">
                <p className="text-sm text-amber-100">{review.corrected_root_cause}</p>
              </Meta>
            )}
          </div>
        </Panel>

        {/* --- the approved diagnosis and the fix that follows from it ---------------- */}
        <Panel label="Approved diagnosis" title="Root cause and recommended fix">
          <div className="space-y-4">
            <Meta label="Root cause">
              <p className="leading-relaxed">
                {review.corrected_root_cause || diagnosis.ai.root_cause}
              </p>
            </Meta>
            <div className="flex flex-wrap gap-2">
              <Badge tone="violet">
                {review.corrected_category || diagnosis.ai.category}
              </Badge>
              <Badge>{review.corrected_osi_layer || diagnosis.ai.osi_layer}</Badge>
              <Badge tone="sky">effective: {diagnosis.confidence.effective_confidence}</Badge>
            </div>

            <Meta label="Recommended fix">
              {fixSteps.length > 0 ? (
                <ol className="list-decimal space-y-1 pl-5 font-mono text-xs text-slate-300">
                  {fixSteps.map((step, index) => (
                    <li key={index}>{step}</li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-slate-500">No fix steps were proposed.</p>
              )}
            </Meta>

            <Meta label="Findings the simulator will address">
              <div className="flex flex-wrap gap-1.5">
                {targetedRuleIds.map((ruleId) => (
                  <Badge key={ruleId} tone="sky">
                    {ruleId}
                  </Badge>
                ))}
              </div>
              <p className="mt-2 text-xs text-slate-500">
                Mutations are derived from these deterministic findings. This interface cannot
                describe a change of its own — the request carries a review id and nothing
                else.
              </p>
            </Meta>
          </div>
        </Panel>
      </div>

      {/* --- apply --------------------------------------------------------------------- */}
      {!run && (
        <Panel
          tone={permitted ? 'warn' : 'danger'}
          label="Step 5 — Simulated fix"
          title={permitted ? 'Apply the approved fix' : 'No fix can be applied'}
        >
          {permitted ? (
            <div className="space-y-3">
              <div className="rounded-md border-2 border-sky-700 bg-sky-950/40 px-4 py-3">
                <p className="text-sm font-bold uppercase tracking-wide text-sky-200">
                  Simulation only
                </p>
                <p className="mt-1 text-sm text-sky-100/90">
                  This is not a real network operation. The fix is applied to a deep copy of
                  the structured lab model, and verification re-runs the deterministic rule
                  engine over that copy. Nothing is sent to a device — there is no SSH,
                  Telnet or command execution anywhere in this system.
                </p>
              </div>
              <Button onClick={apply} busy={applying}>
                Apply Fix to Simulated Lab
              </Button>
              {applying && <Loading label="Applying mutations and re-running the rule engine…" />}
              <ErrorNotice error={applyError} />
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-base font-bold uppercase tracking-wide text-rose-200">
                Diagnosis rejected. No fix can be applied.
              </p>
              <p className="text-sm text-rose-100/90">
                The recorded verdict is <strong>{review.verdict}</strong>. The backend refuses
                an apply request for this diagnosis with HTTP 409, so there is nothing this
                page could do to proceed.
              </p>
              <Link
                to={`/cases/${diagnosis.case_id}`}
                className="inline-block text-sm text-sky-300 hover:underline"
              >
                ← Back to the Triage Workbench
              </Link>
            </div>
          )}
        </Panel>
      )}

      {/* --- verification -------------------------------------------------------------- */}
      {run && (
        <Panel
          tone="deterministic"
          label="Step 6 — Deterministic verification"
          title="Before and after, re-checked by the rule engine"
        >
          <FixVerificationCard run={run} />
        </Panel>
      )}
    </div>
  )
}

export default FixVerify
