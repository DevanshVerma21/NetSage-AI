import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { createReview, getDiagnosis } from '../api/client.js'
import { AIDiagnosisCard } from '../components/AIDiagnosisCard.jsx'
import { RuleFindingCard } from '../components/RuleFindingCard.jsx'
import { ReviewForm } from '../components/ReviewForm.jsx'
import { StatusBadge, VerdictBadge } from '../components/StatusBadge.jsx'
import { Button, ErrorNotice, Loading, Panel } from '../components/ui.jsx'

/**
 * The human review gate.
 *
 * The verdict is submitted to `POST /api/reviews` and nothing is treated as approved until
 * that call succeeds. An accepted or edited review leads on to Fix & Verify; a rejection
 * deliberately leads nowhere, and says so.
 *
 * A diagnosis is reviewed exactly once. If one already carries a verdict this page shows it
 * instead of offering the form, because a second submission is a 409 by design — the audit
 * trail is not overwritten.
 */
export function HumanReview() {
  const { diagnosisId } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()

  const [diagnosis, setDiagnosis] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [loading, setLoading] = useState(true)

  const initialVerdict = ['accepted', 'edited', 'rejected'].includes(params.get('verdict'))
    ? params.get('verdict')
    : 'accepted'
  const [verdict, setVerdict] = useState(initialVerdict)

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [rejected, setRejected] = useState(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    getDiagnosis(diagnosisId)
      .then((data) => active && setDiagnosis(data))
      .catch((error) => active && setLoadError(error))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [diagnosisId])

  async function submit(payload) {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const review = await createReview(payload)
      if (review.verdict === 'rejected') {
        // No navigation: a rejected diagnosis has no fix page to go to.
        setRejected(review)
        setDiagnosis(await getDiagnosis(diagnosisId))
      } else {
        navigate(`/fixes/${review.review_id}`)
      }
    } catch (error) {
      setSubmitError(error)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <Loading label="Loading the diagnosis…" />
  if (loadError) {
    return (
      <div className="space-y-4">
        <ErrorNotice error={loadError} />
        <Link to="/" className="text-sm text-sky-400 hover:underline">
          ← Back to the case library
        </Link>
      </div>
    )
  }
  if (!diagnosis) return null

  const alreadyReviewed = diagnosis.status !== 'awaiting_human_review'

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
          <h2 className="mt-1 text-xl font-semibold text-slate-50">Human Review</h2>
          <p className="mt-1 font-mono text-xs text-slate-500">{diagnosis.diagnosis_id}</p>
        </div>
        <StatusBadge status={diagnosis.status} applied={diagnosis.applied} />
      </div>

      {/* The rejection outcome, shown in place of the form once recorded. */}
      {rejected && (
        <div className="rounded-md border-2 border-rose-700 bg-rose-950/45 px-4 py-4">
          <p className="text-base font-bold uppercase tracking-wide text-rose-200">
            Diagnosis rejected. No fix can be applied.
          </p>
          <p className="mt-1 text-sm text-rose-100/90">
            Recorded as {rejected.review_id} ({rejected.reason_code}). The backend will refuse
            any attempt to apply a fix from this diagnosis with HTTP 409.
          </p>
          <Link
            to={`/cases/${diagnosis.case_id}`}
            className="mt-3 inline-block text-sm text-sky-300 hover:underline"
          >
            ← Back to the Triage Workbench
          </Link>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-5">
          <Panel
            tone="ai"
            label="Under review — an AI proposal"
            title="AI diagnosis and evidence"
          >
            <AIDiagnosisCard diagnosis={diagnosis} />
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel
            tone="deterministic"
            label="Deterministic Rule Engine"
            title={`${diagnosis.rule_findings.length} finding(s) — ${
              diagnosis.rule_ids?.join(', ') ||
              [...new Set(diagnosis.rule_findings.map((f) => f.rule_id))].sort().join(', ') ||
              'none'
            }`}
            subtitle="What the engine found independently of the model. These are also the only source of the simulated fix."
          >
            <div className="space-y-2">
              {diagnosis.rule_findings.map((finding, index) => (
                <RuleFindingCard key={index} finding={finding} />
              ))}
            </div>
          </Panel>

          {alreadyReviewed && !rejected ? (
            <Panel label="Verdict already recorded" title="This diagnosis has been reviewed">
              <div className="space-y-3">
                <VerdictBadge verdict={diagnosis.status} />
                <p className="text-sm text-slate-300">
                  A diagnosis is reviewed once — the audit trail is not overwritten, and a
                  second verdict would be refused with HTTP 409.
                </p>
                {diagnosis.status === 'rejected' ? (
                  <p className="text-sm font-semibold text-rose-200">
                    Diagnosis rejected. No fix can be applied.
                  </p>
                ) : (
                  <Button onClick={() => navigate(`/fixes/${diagnosis.review_id}`)}>
                    Go to Fix &amp; Verify →
                  </Button>
                )}
              </div>
            </Panel>
          ) : (
            !rejected && (
              <Panel
                tone="warn"
                label="Step 4 — Human review is mandatory"
                title="Record your verdict"
                subtitle="Submitted to POST /api/reviews. Nothing is approved in this browser."
              >
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {[
                      ['accepted', 'Accept', 'accept'],
                      ['edited', 'Edit', 'edit'],
                      ['rejected', 'Reject', 'reject'],
                    ].map(([value, label, variant]) => (
                      <Button
                        key={value}
                        variant={verdict === value ? variant : 'ghost'}
                        onClick={() => {
                          setVerdict(value)
                          setSubmitError(null)
                        }}
                        type="button"
                      >
                        {label}
                      </Button>
                    ))}
                  </div>

                  <ReviewForm
                    key={verdict}
                    diagnosis={diagnosis}
                    verdict={verdict}
                    busy={submitting}
                    error={submitError}
                    onSubmit={submit}
                  />
                </div>
              </Panel>
            )
          )}
        </div>
      </div>
    </div>
  )
}

export default HumanReview
