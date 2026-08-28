import { Link, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ResponsibleAI from './pages/ResponsibleAI.jsx'
import { CaseLibrary } from './pages/CaseLibrary.jsx'
import { TriageWorkbench } from './pages/TriageWorkbench.jsx'
import { HumanReview } from './pages/HumanReview.jsx'
import ReviewQueue from './pages/ReviewQueue.jsx'
import { FixVerify } from './pages/FixVerify.jsx'

/**
 * The workflow is four routes — case library → triage → human review → simulated fix and
 * verification — and the two read-only disclosure pages sit either side of it.
 *
 * `/` is the Dashboard rather than the case library, so the first thing anyone sees is the
 * real coverage status: the deterministic rules ran over every case, the AI evaluation did
 * not. The library moved to `/cases`, which also makes it the parent path of `/cases/:caseId`.
 */
function NotFound() {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-10 text-center">
      <p className="text-sm text-slate-300">That page does not exist.</p>
      <Link to="/cases" className="mt-2 inline-block text-sm text-sky-400 hover:underline">
        ← Back to the case library
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/responsible-ai" element={<ResponsibleAI />} />
        <Route path="/review" element={<ReviewQueue />} />
        <Route path="/cases" element={<CaseLibrary />} />
        <Route path="/cases/:caseId" element={<TriageWorkbench />} />
        <Route path="/review/:diagnosisId" element={<HumanReview />} />
        <Route path="/fixes/:reviewId" element={<FixVerify />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}
