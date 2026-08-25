import { Link, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell.jsx'
import { CaseLibrary } from './pages/CaseLibrary.jsx'
import { TriageWorkbench } from './pages/TriageWorkbench.jsx'
import { HumanReview } from './pages/HumanReview.jsx'
import { FixVerify } from './pages/FixVerify.jsx'

/**
 * Four routes, which are the four stages of the workflow:
 * case library → triage → human review → simulated fix and verification.
 *
 * The Dashboard and Responsible-AI pages are deliberately absent; they belong to a later
 * phase and would need metrics computed from a larger body of stored reviews than exists yet.
 */
function NotFound() {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-10 text-center">
      <p className="text-sm text-slate-300">That page does not exist.</p>
      <Link to="/" className="mt-2 inline-block text-sm text-sky-400 hover:underline">
        ← Back to the case library
      </Link>
    </div>
  )
}

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<CaseLibrary />} />
        <Route path="/cases/:caseId" element={<TriageWorkbench />} />
        <Route path="/review/:diagnosisId" element={<HumanReview />} />
        <Route path="/fixes/:reviewId" element={<FixVerify />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}
