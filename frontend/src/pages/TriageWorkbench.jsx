import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { checkRules, diagnose, getCase, getDiagnoses, getHealth } from '../api/client.js'
import { AIDiagnosisCard } from '../components/AIDiagnosisCard.jsx'
import { RuleFindingCard, RulePassRow } from '../components/RuleFindingCard.jsx'
import { ShowOutputViewer } from '../components/ShowOutputViewer.jsx'
import { Badge, SeverityBadge, StatusBadge } from '../components/StatusBadge.jsx'
import { Button, ErrorNotice, Loading, Meta, Panel } from '../components/ui.jsx'

/**
 * The Triage Workbench.
 *
 * The column order is the argument: evidence on the left, and on the right the deterministic
 * findings *above* the AI proposal, because that is the order in which the two halves earn
 * trust. The rule check runs automatically on load — it costs nothing, involves no model, and
 * an operator should see what the engine found before being shown what a model thinks.
 *
 * No fix control appears on this page at any point. The route to a fix runs through a
 * recorded human verdict, and the button does not exist until one is on file.
 */
export function TriageWorkbench() {
  const { caseId } = useParams()
  const navigate = useNavigate()

  const [caseData, setCaseData] = useState(null)
  const [caseError, setCaseError] = useState(null)
  const [loadingCase, setLoadingCase] = useState(true)

  const [rules, setRules] = useState(null)
  const [rulesError, setRulesError] = useState(null)
  const [runningRules, setRunningRules] = useState(false)

  const [diagnosis, setDiagnosis] = useState(null)
  const [diagnosisError, setDiagnosisError] = useState(null)
  const [runningAI, setRunningAI] = useState(false)

  const [mandatoryRules, setMandatoryRules] = useState([])
  const [provider, setProvider] = useState('mock')
  const [health, setHealth] = useState(null)

  const runRules = useCallback(async () => {
    setRunningRules(true)
    setRulesError(null)
    try {
      setRules(await checkRules(caseId))
    } catch (error) {
      setRulesError(error)
    } finally {
      setRunningRules(false)
    }
  }, [caseId])

  useEffect(() => {
    let active = true
    setLoadingCase(true)
    setCaseError(null)
    setDiagnosis(null)
    getCase(caseId)
      .then((data) => {
        if (!active) return
        setCaseData(data)
        runRules()
      })
      .catch((error) => active && setCaseError(error))
      .finally(() => active && setLoadingCase(false))
    return () => {
      active = false
    }
  }, [caseId, runRules])

  useEffect(() => {
    getHealth()
      .then((data) => {
        setHealth(data)
        setMandatoryRules(data.mandatory_rules || [])
      })
      .catch(() => {})
  }, [])

  // A diagnosis already on file for this case is shown rather than silently re-run: a
  // proposal that is awaiting review should not be quietly duplicated by a page refresh.
  useEffect(() => {
    let active = true
    getDiagnoses({ case_id: caseId })
      .then((records) => {
        if (active && records.length > 0) setDiagnosis(records[records.length - 1])
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [caseId])

  async function runDiagnosis() {
    setRunningAI(true)
    setDiagnosisError(null)
    try {
      setDiagnosis(await diagnose(caseId, provider))
    } catch (error) {
      setDiagnosisError(error)
    } finally {
      setRunningAI(false)
    }
  }

  if (loadingCase) return <Loading label={`Loading ${caseId}…`} />
  if (caseError) {
    return (
      <div className="space-y-4">
        <ErrorNotice error={caseError} />
        <Link to="/" className="text-sm text-sky-400 hover:underline">
          ← Back to the case library
        </Link>
      </div>
    )
  }
  if (!caseData) return null

  const firedRuleIds = new Set(rules?.rule_ids || [])
  const passing = mandatoryRules.filter((ruleId) => !firedRuleIds.has(ruleId))
  const awaitingReview = diagnosis?.status === 'awaiting_human_review'

  return (
    <div className="space-y-5">
      {/* --- header ------------------------------------------------------------------- */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/" className="text-xs text-sky-400 hover:underline">
            ← Case Library
          </Link>
          <h2 className="mt-1 text-xl font-semibold text-slate-50">
            <span className="font-mono text-sky-300">{caseData.case_id}</span>{' '}
            {caseData.title}
          </h2>
          <p className="mt-1 text-xs uppercase tracking-[0.14em] text-slate-500">
            Triage Workbench
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="violet">{caseData.concept_tag}</Badge>
          <SeverityBadge severity={caseData.severity} />
          <Badge>{caseData.osi_layer}</Badge>
          <Badge tone="sky">{caseData.source_label}</Badge>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* --- LEFT: the evidence ----------------------------------------------------- */}
        <div className="space-y-5">
          <Panel label="Step 1 — Evidence" title="Case information">
            <div className="space-y-4">
              <Meta label="Symptom">
                <p className="leading-relaxed">{caseData.symptom}</p>
              </Meta>
              <Meta label="Topology note">
                <p className="leading-relaxed text-slate-300">{caseData.topology_note}</p>
              </Meta>
              {caseData.intended_flows?.length > 0 && (
                <Meta label="Intended flows">
                  <ul className="space-y-1 font-mono text-xs text-slate-300">
                    {caseData.intended_flows.map((flow, index) => (
                      <li key={index}>
                        {flow.src} → {flow.dst} {flow.proto}
                        {flow.port ? `/${flow.port}` : ''}{' '}
                        <span
                          className={
                            flow.expect === 'permit' ? 'text-emerald-300' : 'text-rose-300'
                          }
                        >
                          {flow.expect}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Meta>
              )}
            </div>
          </Panel>

          <Panel
            label="Show command evidence"
            title="Captured device output"
            subtitle="The exact text supplied to the AI and searched by the evidence verifier. Nothing is truncated."
          >
            <ShowOutputViewer outputs={caseData.show_outputs} />
          </Panel>
        </div>

        {/* --- RIGHT: rules, then AI, then the gate ----------------------------------- */}
        <div className="space-y-5">
          <Panel
            tone="deterministic"
            label="Step 2 — Deterministic Rule Engine"
            title="Rule check"
            subtitle="Pure Python over the structured lab state. No AI is involved on this path."
            right={
              <div className="flex items-center gap-2">
                {rules && <Badge tone="sky">ai_used: {String(rules.ai_used)}</Badge>}
                <Button variant="ghost" onClick={runRules} busy={runningRules}>
                  Re-run
                </Button>
              </div>
            }
          >
            {runningRules && !rules ? (
              <Loading label="Running the deterministic rule checker…" />
            ) : (
              <>
                <ErrorNotice error={rulesError} className="mb-3" />
                {rules && (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-300">
                      {rules.finding_count === 0
                        ? 'No deterministic finding on this topology.'
                        : `${rules.finding_count} finding${
                            rules.finding_count === 1 ? '' : 's'
                          } across ${rules.rule_ids.length} rule${
                            rules.rule_ids.length === 1 ? '' : 's'
                          }: ${rules.rule_ids.join(', ')}.`}
                    </p>

                    {rules.findings.map((finding, index) => (
                      <RuleFindingCard key={index} finding={finding} />
                    ))}

                    {passing.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
                          Mandatory rules that found nothing
                        </p>
                        <div className="grid gap-1.5 sm:grid-cols-2">
                          {passing.map((ruleId) => (
                            <RulePassRow key={ruleId} ruleId={ruleId} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </Panel>

          <Panel
            tone="ai"
            label="Step 3 — AI Diagnosis (a proposal)"
            title="Language-model reasoning over the show output"
            subtitle="Checked afterwards by the evidence verifier and reconciled against the rule engine. Never applied."
            right={
              diagnosis ? (
                <StatusBadge status={diagnosis.status} applied={diagnosis.applied} />
              ) : null
            }
          >
            {!diagnosis && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={runDiagnosis} busy={runningAI}>
                    Run AI Diagnosis
                  </Button>
                  <label className="flex items-center gap-2 text-xs text-slate-400">
                    Provider
                    <select
                      className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                      value={provider}
                      onChange={(event) => setProvider(event.target.value)}
                      disabled={runningAI}
                    >
                      <option value="mock">mock (offline, deterministic)</option>
                      <option value="gemini">
                        gemini{health?.provider_configured ? '' : ' — no key configured'}
                      </option>
                    </select>
                  </label>
                </div>
                {runningAI && <Loading label="Running the AI pipeline…" />}
                <ErrorNotice error={diagnosisError} />
                {!runningAI && !diagnosisError && (
                  <p className="text-xs text-slate-500">
                    The proposal will be stored as <code>awaiting_human_review</code> with{' '}
                    <code>applied: false</code>. No fix can follow from it without a recorded
                    human verdict.
                  </p>
                )}
              </div>
            )}

            {diagnosis && (
              <div className="space-y-4">
                <AIDiagnosisCard diagnosis={diagnosis} />
                <ErrorNotice error={diagnosisError} />
              </div>
            )}
          </Panel>

          {/* --- Step 4: the human gate --------------------------------------------- */}
          {diagnosis && (
            <Panel
              tone={awaitingReview ? 'warn' : 'default'}
              label="Step 4 — Human review"
              title={awaitingReview ? 'Human review required' : 'Reviewed'}
            >
              {awaitingReview ? (
                <div className="space-y-3">
                  <div className="rounded-md border-2 border-dashed border-amber-500/80 bg-amber-950/25 px-4 py-3">
                    <p className="text-sm font-bold uppercase tracking-wide text-amber-200">
                      Human review required
                    </p>
                    <p className="mt-1 text-sm text-amber-100/90">
                      Proposed — awaiting human review. This diagnosis has not been approved,
                      and no fix can be simulated until a verdict is recorded on the server.
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="accept"
                      onClick={() => navigate(`/review/${diagnosis.diagnosis_id}`)}
                    >
                      Accept
                    </Button>
                    <Button
                      variant="edit"
                      onClick={() =>
                        navigate(`/review/${diagnosis.diagnosis_id}?verdict=edited`)
                      }
                    >
                      Edit
                    </Button>
                    <Button
                      variant="reject"
                      onClick={() =>
                        navigate(`/review/${diagnosis.diagnosis_id}?verdict=rejected`)
                      }
                    >
                      Reject
                    </Button>
                  </div>
                  <p className="text-xs text-slate-400">
                    Each verdict is recorded through <code>POST /api/reviews</code>. The gate
                    is enforced by the backend from stored records, not by this interface.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  <StatusBadge status={diagnosis.status} applied={diagnosis.applied} />
                  {diagnosis.status === 'rejected' ? (
                    <p className="text-sm text-rose-200">
                      Diagnosis rejected. No fix can be applied.
                    </p>
                  ) : (
                    <Link
                      to={`/fixes/${diagnosis.review_id}`}
                      className="inline-block rounded-md border border-sky-500 bg-sky-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-sky-500"
                    >
                      Go to Fix &amp; Verify →
                    </Link>
                  )}
                  <p className="text-xs text-slate-500">
                    Review {diagnosis.review_id}
                  </p>
                </div>
              )}
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}

export default TriageWorkbench
