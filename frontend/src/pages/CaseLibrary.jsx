import { useEffect, useMemo, useState } from 'react'
import { getCases } from '../api/client.js'
import { CaseTable } from '../components/CaseTable.jsx'
import { ErrorNotice, Loading, Panel, inputClass } from '../components/ui.jsx'

/**
 * The case library.
 *
 * Filtering is done server-side through the query parameters `/api/cases` already supports,
 * so the list stays correct when the dataset grows past one case. The filter *options* are
 * derived from the cases the backend returned rather than hard-coded, so nothing here has to
 * be edited when Phase 5 expands the dataset.
 */
export function CaseLibrary() {
  const [cases, setCases] = useState([])
  const [allCases, setAllCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [severity, setSeverity] = useState('')

  // The unfiltered set, fetched once, is the source of the filter dropdowns.
  useEffect(() => {
    getCases()
      .then(setAllCases)
      .catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const handle = setTimeout(() => {
      getCases({ q, category, severity })
        .then((data) => active && setCases(data))
        .catch((err) => active && setError(err))
        .finally(() => active && setLoading(false))
    }, 200) // debounce the search box
    return () => {
      active = false
      clearTimeout(handle)
    }
  }, [q, category, severity])

  const categories = useMemo(
    () => [...new Set(allCases.map((item) => item.concept_tag))].sort(),
    [allCases],
  )
  const severities = useMemo(() => {
    const order = ['Critical', 'High', 'Medium', 'Low']
    const present = new Set(allCases.map((item) => item.severity))
    return order.filter((level) => present.has(level))
  }, [allCases])

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-slate-50">Case Library</h2>
        <p className="mt-1 text-sm text-slate-400">
          Simulated lab faults. Open a case to see its evidence, run the deterministic rule
          engine, and request an AI diagnosis for human review.
        </p>
      </div>

      <Panel
        label="Filters"
        right={
          <span className="text-xs text-slate-500">
            {loading ? 'Loading…' : `${cases.length} of ${allCases.length} shown`}
          </span>
        }
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <input
            className={inputClass}
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Search title, symptom or topology…"
            aria-label="Search cases"
          />
          <select
            className={inputClass}
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            aria-label="Filter by category"
          >
            <option value="">All categories</option>
            {categories.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
          <select
            className={inputClass}
            value={severity}
            onChange={(event) => setSeverity(event.target.value)}
            aria-label="Filter by severity"
          >
            <option value="">All severities</option>
            {severities.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </div>
      </Panel>

      <ErrorNotice error={error} />

      <Panel label="Cases">
        {loading ? <Loading label="Loading cases…" /> : <CaseTable cases={cases} />}
      </Panel>
    </div>
  )
}

export default CaseLibrary
