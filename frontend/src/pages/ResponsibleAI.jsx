/**
 * The Responsible AI disclosures — methodology, evidence verification, confidence capping,
 * the mandatory human gate, execution scope, evaluation status, known limitations, and the
 * human-correction log.
 *
 * Everything here comes from `GET /api/responsible-ai`. The two things the page is most
 * careful about: the evaluation status is reported before anything that could be read as a
 * quality claim, and the correction log renders an explicit empty state rather than example
 * entries when no genuine human correction exists.
 */

import { useEffect, useState } from 'react'

import { getResponsibleAI } from '../api/client.js'
import { Panel, Loading, ErrorNotice, Meta } from '../components/ui.jsx'
import { Badge } from '../components/StatusBadge.jsx'
import { CoverageBanner, EmptyState, LimitationItem, SourceNote, Stat } from '../components/Metrics.jsx'

function NumberedList({ items }) {
  return (
    <ol className="space-y-2">
      {items.map((text, index) => (
        <li key={index} className="flex gap-2.5 text-xs leading-relaxed text-slate-300">
          <span className="mt-px font-mono text-[10px] font-semibold text-slate-500">
            {String(index + 1).padStart(2, '0')}
          </span>
          <span>{text}</span>
        </li>
      ))}
    </ol>
  )
}

function Bullets({ items, tone = 'slate' }) {
  const dot = { slate: 'bg-slate-600', emerald: 'bg-emerald-500', rose: 'bg-rose-500' }
  return (
    <ul className="space-y-1.5">
      {items.map((text, index) => (
        <li key={index} className="flex gap-2.5 text-xs leading-relaxed text-slate-300">
          <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${dot[tone] || dot.slate}`} />
          <span>{text}</span>
        </li>
      ))}
    </ul>
  )
}

function CorrectionEntry({ entry }) {
  return (
    <li className="rounded-md border border-slate-800 bg-slate-950/50 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-mono text-sm font-semibold text-slate-100">{entry.case_id}</p>
        {entry.human_decision && <Badge tone="amber">{entry.human_decision}</Badge>}
        {entry.reason && <Badge tone="slate">{entry.reason}</Badge>}
      </div>
      <div className="mt-2.5 grid gap-3 lg:grid-cols-2">
        <Meta label="What the AI said">
          <p className="text-xs leading-relaxed text-violet-200">{entry.ai_output || '—'}</p>
        </Meta>
        <Meta label="The human correction">
          <p className="text-xs leading-relaxed text-emerald-200">{entry.correction || '—'}</p>
        </Meta>
      </div>
      {entry.lesson && (
        <p className="mt-2.5 border-t border-slate-800/70 pt-2 text-xs leading-relaxed text-slate-400">
          <span className="font-semibold text-slate-300">Lesson: </span>
          {entry.lesson}
        </p>
      )}
    </li>
  )
}

export default function ResponsibleAI() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    getResponsibleAI()
      .then((payload) => live && setData(payload))
      .catch((err) => live && setError(err))
    return () => {
      live = false
    }
  }, [])

  if (error) return <ErrorNotice error={error} />
  if (!data) return <Loading label="Loading the Responsible AI disclosures…" />

  const { ai_evaluation: ai, human_review: hr, log, methodology: m, execution_scope: scope } = data

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-lg font-semibold text-slate-100">Responsible AI</h1>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-400">
          How a diagnosis is produced, what is checked deterministically, what the system is
          not permitted to do, and where it is currently incomplete. The evaluation status is
          stated first on purpose.
        </p>
      </header>

      <CoverageBanner ai={ai} />

      {/* ---- evaluation status ------------------------------------------------------- */}
      <Panel tone="ai" label="Status" title="Evaluation status">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="AI evaluation" value={ai.evaluated} of={ai.total} tone="ai" />
          <Stat label="Remaining" value={ai.remaining} tone="warn" />
          <Stat
            label="Status"
            value={<span className="text-sm">{ai.status}</span>}
            tone={ai.coverage_complete ? 'good' : 'warn'}
          />
          <Stat
            label="Human reviews"
            value={hr.total_reviews}
            tone={hr.total_reviews ? 'default' : 'muted'}
            hint={`${hr.corrections}/${hr.required_corrections} genuine corrections`}
          />
          <Stat label="Accepted" value={hr.accepted} />
          <Stat label="Edited" value={hr.edited} />
          <Stat label="Rejected" value={hr.rejected} />
          <Stat label="Genuine corrections" value={`${hr.corrections}/${hr.required_corrections}`} tone="warn" />
        </div>
        <SourceNote>{ai.accuracy_note}</SourceNote>
      </Panel>

      {/* ---- methodology ------------------------------------------------------------ */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel label="Methodology" title="How a diagnosis is produced">
          <NumberedList items={m.pipeline} />
          <SourceNote>
            {m.grading_note} Prompt identity is recorded with every stored diagnosis:{' '}
            {Object.entries(m.prompts)
              .map(([name, entry]) => `${name} v${entry.version}`)
              .join(' · ')}
            .
          </SourceNote>
        </Panel>

        <Panel label="Methodology" title="How a result is graded">
          <NumberedList items={m.grading} />
          <SourceNote>{m.prompt_note}</SourceNote>
        </Panel>

        <Panel tone="deterministic" label="Deterministic" title="Evidence verification">
          <div className="space-y-3">
            <Meta label="Rule">
              <p className="text-xs leading-relaxed text-slate-300">
                {m.evidence_verification.rule}
              </p>
            </Meta>
            <Meta label="Normalisation">
              <p className="text-xs leading-relaxed text-slate-300">
                {m.evidence_verification.normalisation}
              </p>
            </Meta>
            <Meta label="On failure">
              <p className="text-xs leading-relaxed text-slate-300">
                {m.evidence_verification.on_failure}
              </p>
            </Meta>
            <div className="flex flex-wrap gap-1.5">
              {m.evidence_verification.statuses.map((s) => (
                <Badge key={s} tone="sky">
                  {s}
                </Badge>
              ))}
            </div>
          </div>
        </Panel>

        <Panel tone="deterministic" label="Deterministic" title="Confidence capping">
          <p className="text-xs leading-relaxed text-slate-300">{m.confidence_capping.rule}</p>
          <div className="mt-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
              Triggers
            </p>
            <div className="mt-2">
              <Bullets items={m.confidence_capping.triggers} />
            </div>
          </div>
        </Panel>
      </div>

      {/* ---- human gate ------------------------------------------------------------- */}
      <Panel
        label="Human gate"
        title="Human review is mandatory"
        right={<Badge tone="emerald">enforced server-side</Badge>}
      >
        <p className="text-xs leading-relaxed text-slate-300">{m.human_review.rule}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Meta label="Verdicts">
            <div className="flex flex-wrap gap-1.5">
              {m.human_review.verdicts.map((v) => (
                <Badge key={v} tone="slate">
                  {v}
                </Badge>
              ))}
            </div>
          </Meta>
          <Meta label="Gate">
            <p className="text-xs leading-relaxed text-slate-300">{m.human_review.gate}</p>
          </Meta>
        </div>
      </Panel>

      {/* ---- execution scope -------------------------------------------------------- */}
      <Panel
        tone="warn"
        label="Execution scope"
        title={scope.scope}
        subtitle={scope.disclaimer}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-emerald-300/80">
              What this system can do
            </p>
            <div className="mt-2">
              <Bullets items={scope.can} tone="emerald" />
            </div>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-rose-300/80">
              What it cannot do
            </p>
            <div className="mt-2">
              <Bullets items={scope.cannot} tone="rose" />
            </div>
          </div>
        </div>
      </Panel>

      {/* ---- correction log --------------------------------------------------------- */}
      <Panel
        label="Human corrections"
        title="Responsible AI log"
        subtitle={`${log.total_corrections}/${log.required_corrections} genuine corrections recorded`}
        tone={log.available ? 'default' : 'warn'}
      >
        {log.available ? (
          <>
            <ul className="space-y-3">
              {log.corrections.map((entry, index) => (
                <CorrectionEntry key={entry.case_id || index} entry={entry} />
              ))}
            </ul>
            {log.note && <SourceNote>{log.note}</SourceNote>}
          </>
        ) : (
          <EmptyState title="Human review data incomplete">
            <p>{log.empty_state}</p>
          </EmptyState>
        )}
      </Panel>

      {/* ---- limitations ------------------------------------------------------------ */}
      <Panel
        tone="danger"
        label="Disclosure"
        title="Known limitations"
        subtitle="The blockers that actually apply to the stored data are listed first."
      >
        <ul>
          {data.limitations.map((item) => (
            <LimitationItem key={item.title} item={item} />
          ))}
        </ul>
      </Panel>
    </div>
  )
}
