/**
 * The two read-only case-detail blocks Phase 7 adds to the Triage Workbench.
 *
 * `GroundTruthPanel` shows the stored expectation for the case. It is displayed *after* the
 * evidence and the rule findings, and it is never sent to the model — the AI is graded
 * against it, so a page that showed it as an input would be describing a different system.
 *
 * `StoredEvaluationPanel` renders whatever `GET /api/evaluations?case_id=` returned. When
 * that is an empty list it says so, in those words, and shows nothing else. There is no
 * placeholder result, and an invalidated row is labelled as not official rather than counted.
 */

import { Badge } from './StatusBadge.jsx'
import { Meta, Panel } from './ui.jsx'
import { EmptyState, SourceNote } from './Metrics.jsx'

const RESULT_TONE = {
  CORRECT: 'emerald',
  PARTIAL: 'amber',
  INCORRECT: 'rose',
  UNABLE_TO_EVALUATE: 'slate',
}

const CONFIDENCE_TONE = { high: 'emerald', medium: 'amber', low: 'rose' }

// `evidence_integrity` is the verifier's own vocabulary — passed / partial / failed. Kept
// distinct from the fix-verification badge, which describes a different check entirely.
const INTEGRITY_TONE = { passed: 'emerald', partial: 'amber', failed: 'rose' }

export function GroundTruthPanel({ caseData }) {
  return (
    <Panel
      label="Ground truth"
      title="The stored expectation for this case"
      subtitle="Written when the case was authored. Never supplied to the model, and never changed after seeing a model answer."
    >
      <div className="space-y-4">
        <Meta label="Expected fault">
          <p className="leading-relaxed">{caseData.expected_fault}</p>
        </Meta>
        <div className="grid gap-4 sm:grid-cols-2">
          <Meta label="Expected rule ids">
            <p className="font-mono text-xs text-sky-200">
              {caseData.expected_rule_ids?.length
                ? caseData.expected_rule_ids.join(' · ')
                : 'none'}
            </p>
          </Meta>
          <Meta label="Root-cause keywords">
            <p className="text-xs leading-relaxed text-slate-300">
              {caseData.expected_root_cause_keywords?.join(', ') || 'none'}
            </p>
          </Meta>
        </div>
        {caseData.expected_fix_steps?.length > 0 && (
          <Meta label="Expected fix steps">
            <ol className="space-y-1 font-mono text-xs text-slate-300">
              {caseData.expected_fix_steps.map((step, index) => (
                <li key={index}>
                  <span className="mr-1.5 text-slate-600">{index + 1}.</span>
                  {step}
                </li>
              ))}
            </ol>
          </Meta>
        )}
      </div>
      <SourceNote>
        DETERMINISTIC — a declared expectation, not an independently observed outcome. It is
        what the grader compares an AI answer against.
      </SourceNote>
    </Panel>
  )
}

function AgreementRow({ label, ok }) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="text-slate-300">{label}</span>
      <Badge tone={ok ? 'emerald' : 'rose'}>{ok ? 'agrees' : 'differs'}</Badge>
    </div>
  )
}

export function StoredEvaluationPanel({ records, loading }) {
  if (loading) return null

  if (!records || records.length === 0) {
    return (
      <Panel tone="ai" label="AI evaluation" title="Stored evaluation record">
        <EmptyState title="AI evaluation not available for this case">
          <p>
            No evaluation record is stored for this case, so nothing is shown here. The Gemini
            free tier caps this project at 20 requests per day, which stopped the 40-case
            batch. No placeholder result was generated in its place.
          </p>
        </EmptyState>
      </Panel>
    )
  }

  const record = records[records.length - 1]
  const official = record.evaluation_status === 'completed' && !record.invalidated

  return (
    <Panel
      tone="ai"
      label="AI evaluation"
      title="Stored evaluation record"
      subtitle={`${record.provider} · ${record.model} · prompt ${record.prompt_version}`}
      right={
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={RESULT_TONE[record.evaluation_result] || 'slate'}>
            {record.evaluation_result}
          </Badge>
          {!official && <Badge tone="rose">not official</Badge>}
        </div>
      }
    >
      {record.evaluation_status !== 'completed' ? (
        <div className="rounded-md border border-rose-900/60 bg-rose-950/25 px-3 py-2.5">
          <p className="text-sm font-semibold text-rose-200">
            The provider call failed — {record.error_type || 'error'}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-rose-100/85">
            {record.error_message || 'No message was recorded.'}
          </p>
          <p className="mt-1.5 text-xs text-slate-400">
            {record.attempts} attempt(s). The failure is kept as a record rather than retried
            into a result.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <Meta label="AI root cause">
            <p className="leading-relaxed text-violet-100">{record.ai_root_cause || '—'}</p>
          </Meta>

          <div className="grid gap-3 sm:grid-cols-3">
            <Meta label="Evidence verification">
              <Badge tone={INTEGRITY_TONE[record.evidence_integrity] || 'slate'}>
                {record.evidence_integrity || '—'}
              </Badge>
              <p className="mt-1 font-mono text-xs text-slate-400">
                {record.verified_citations}/{record.total_citations} citations verified
              </p>
            </Meta>
            <Meta label="Confidence">
              <div className="flex items-center gap-1.5">
                <Badge tone={CONFIDENCE_TONE[record.model_confidence] || 'slate'}>
                  model: {record.model_confidence || '—'}
                </Badge>
              </div>
              <div className="mt-1 flex items-center gap-1.5">
                <Badge tone={CONFIDENCE_TONE[record.effective_confidence] || 'slate'}>
                  effective: {record.effective_confidence || '—'}
                </Badge>
              </div>
              {record.confidence_was_capped && (
                <p className="mt-1 text-[11px] text-amber-300">
                  Capped by the deterministic checks
                </p>
              )}
            </Meta>
            <Meta label="Reconciliation">
              <Badge tone={record.reconciliation === 'agree' ? 'emerald' : 'amber'}>
                {record.reconciliation || '—'}
              </Badge>
              <p className="mt-1 text-[11px] leading-snug text-slate-500">
                AI conclusion versus the rule findings
              </p>
            </Meta>
          </div>

          {record.agreement && (
            <div className="space-y-1.5 rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
                Graded against the stored ground truth
              </p>
              <AgreementRow label="Expected rule ids" ok={record.agreement.rule_agreement} />
              <AgreementRow
                label="Root-cause keywords"
                ok={record.agreement.keyword_agreement}
              />
              <AgreementRow label="OSI layer" ok={record.agreement.osi_agreement} />
              <AgreementRow label="Category" ok={record.agreement.category_agreement} />
            </div>
          )}

          {record.classification_reason && (
            <Meta label="Why it was graded this way">
              <p className="text-xs leading-relaxed text-slate-300">
                {record.classification_reason}
              </p>
            </Meta>
          )}
        </div>
      )}

      <SourceNote>
        AI EVALUATION — one stored record, shown as produced. {records.length} record(s) exist
        for this case.
        {record.invalidated && (
          <>
            {' '}
            This record is marked <span className="font-mono">invalidated</span>:{' '}
            {record.invalidated_reason} It is excluded from every official figure and is kept
            for auditability only
            {record.requires_rerun ? ', and is flagged for re-run' : ''}.
          </>
        )}
      </SourceNote>
    </Panel>
  )
}
