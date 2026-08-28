import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getReviewCandidates } from '../api/client.js'
import { Badge } from '../components/StatusBadge.jsx'
import { ErrorNotice, Loading, Panel } from '../components/ui.jsx'

export default function ReviewQueue() {
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getReviewCandidates().then(setCandidates).catch(setError)
  }, [])

  if (error) return <ErrorNotice error={error} />
  if (!candidates) return <Loading label="Loading genuine diagnoses…" />

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold text-slate-50">Human Review Queue</h1>
        <p className="mt-1 text-sm text-slate-400">
          Stored Gemini and Anthropic diagnoses awaiting one human verdict. Mock and reviewed
          records are excluded.
        </p>
      </header>
      <Panel
        label="Candidates"
        title={`${candidates.length} genuine diagnosis${candidates.length === 1 ? '' : 'es'}`}
        tone={candidates.length ? 'ai' : 'warn'}
      >
        {candidates.length ? (
          <ul className="space-y-3">
            {candidates.map((candidate) => (
              <li key={candidate.diagnosis_id} className="rounded-md border border-slate-800 bg-slate-950/50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-sm font-semibold text-slate-100">{candidate.case_id}</p>
                    <p className="mt-1 text-sm text-slate-300">{candidate.root_cause}</p>
                    <p className="mt-2 font-mono text-xs text-slate-500">{candidate.diagnosis_id}</p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="violet">{candidate.provider}</Badge>
                    <Badge tone="slate">{candidate.model}</Badge>
                    <Badge tone="amber">{candidate.reconciliation}</Badge>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-3">
                  <span>AI: {candidate.category} · {candidate.osi_layer}</span>
                  <span>Confidence: {candidate.effective_confidence}</span>
                  <span>Evidence: {candidate.evidence_integrity}</span>
                </div>
                <Link
                  to={`/review/${candidate.diagnosis_id}`}
                  className="mt-3 inline-block rounded-md border border-sky-600 bg-sky-700 px-3 py-2 text-sm font-semibold text-white hover:bg-sky-600"
                >
                  Review diagnosis
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">No genuine pending model diagnoses are stored.</p>
        )}
      </Panel>
    </div>
  )
}