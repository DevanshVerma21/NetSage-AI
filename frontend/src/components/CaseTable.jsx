import { Link } from 'react-router-dom'
import { Badge, SeverityBadge } from './StatusBadge.jsx'

/**
 * The case library list.
 *
 * A table on wide screens and stacked cards on narrow ones — same data, one component, so
 * the two views cannot drift apart.
 */
export function CaseTable({ cases = [] }) {
  if (cases.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-slate-500">
        No case matches these filters.
      </p>
    )
  }

  return (
    <>
      {/* Wide: a dense table, which is how an operator wants to scan a case list. */}
      <table className="hidden w-full border-collapse text-sm md:table">
        <thead>
          <tr className="border-b border-slate-800 text-left text-[11px] uppercase tracking-wider text-slate-500">
            <th className="px-3 py-2 font-semibold">Case</th>
            <th className="px-3 py-2 font-semibold">Title</th>
            <th className="px-3 py-2 font-semibold">Category</th>
            <th className="px-3 py-2 font-semibold">Severity</th>
            <th className="px-3 py-2 font-semibold">OSI</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {cases.map((item) => (
            <tr
              key={item.case_id}
              className="border-b border-slate-800/60 align-top hover:bg-slate-900/50"
            >
              <td className="whitespace-nowrap px-3 py-3 font-mono text-xs text-sky-300">
                {item.case_id}
              </td>
              <td className="px-3 py-3">
                <p className="font-medium text-slate-100">{item.title}</p>
                <p className="mt-0.5 max-w-xl text-xs text-slate-400">{item.symptom}</p>
              </td>
              <td className="px-3 py-3">
                <Badge tone="violet">{item.concept_tag}</Badge>
              </td>
              <td className="px-3 py-3">
                <SeverityBadge severity={item.severity} />
              </td>
              <td className="px-3 py-3">
                <Badge>{item.osi_layer}</Badge>
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-right">
                <Link
                  to={`/cases/${item.case_id}`}
                  className="rounded-md border border-sky-600 bg-sky-950/60 px-3 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-900/70"
                >
                  Open Case
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Narrow: the same rows as cards. */}
      <div className="space-y-3 md:hidden">
        {cases.map((item) => (
          <article
            key={item.case_id}
            className="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-sky-300">{item.case_id}</span>
              <SeverityBadge severity={item.severity} />
            </div>
            <h3 className="mt-2 font-medium text-slate-100">{item.title}</h3>
            <p className="mt-1 text-xs text-slate-400">{item.symptom}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge tone="violet">{item.concept_tag}</Badge>
              <Badge>{item.osi_layer}</Badge>
            </div>
            <Link
              to={`/cases/${item.case_id}`}
              className="mt-4 block rounded-md border border-sky-600 bg-sky-950/60 px-3 py-2 text-center text-xs font-semibold text-sky-200"
            >
              Open Case
            </Link>
          </article>
        ))}
      </div>
    </>
  )
}

export default CaseTable
