/**
 * Shared read-only display pieces for the Dashboard and Responsible AI pages.
 *
 * `Stat` and `Bar` take values that the backend already calculated. Neither derives a
 * percentage from a total it was not given, so a number on screen cannot disagree with the
 * number in the stored record it came from.
 */

import { Badge } from './StatusBadge.jsx'

/** One figure. `of` renders a denominator so a count is never shown without its base. */
export function Stat({ label, value, of, hint, tone = 'default' }) {
  const tones = {
    default: 'text-slate-100',
    deterministic: 'text-sky-200',
    ai: 'text-violet-200',
    warn: 'text-amber-200',
    danger: 'text-rose-200',
    good: 'text-emerald-200',
    muted: 'text-slate-500',
  }
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 px-3 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
        {label}
      </p>
      <p className={`mt-1 font-mono text-xl font-semibold ${tones[tone] || tones.default}`}>
        {value}
        {of !== undefined && of !== null && (
          <span className="ml-0.5 text-sm font-normal text-slate-500">/{of}</span>
        )}
      </p>
      {hint && <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{hint}</p>}
    </div>
  )
}

/** A labelled proportion bar. Renders an explicit "no data" state rather than an empty bar. */
export function Bar({ label, value, total, tone = 'sky' }) {
  const tones = {
    sky: 'bg-sky-500',
    violet: 'bg-violet-500',
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-500',
    slate: 'bg-slate-600',
  }
  const pct = total > 0 ? Math.round((value / total) * 1000) / 10 : null
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-slate-300">{label}</span>
        <span className="font-mono text-slate-400">
          {value}/{total}
          {pct !== null && <span className="ml-1.5 text-slate-500">{pct}%</span>}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        {pct === null ? null : (
          <div
            className={`h-full rounded-full ${tones[tone] || tones.sky}`}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        )}
      </div>
      {pct === null && <p className="mt-1 text-[11px] text-slate-600">No data yet</p>}
    </div>
  )
}

/**
 * The provenance line every metric block carries. An evaluator should be able to see where a
 * number came from without asking, and "DETERMINISTIC" and "AI EVALUATION" are never merged.
 */
export function SourceNote({ children }) {
  return (
    <p className="mt-3 border-t border-slate-800/70 pt-2.5 text-[11px] leading-relaxed text-slate-500">
      {children}
    </p>
  )
}

/** A blank state that says what is missing and refuses to fill it in. */
export function EmptyState({ title, children }) {
  return (
    <div className="rounded-md border border-dashed border-slate-700 bg-slate-950/40 px-4 py-6">
      <p className="text-sm font-semibold text-slate-300">{title}</p>
      {children && <div className="mt-1.5 text-xs leading-relaxed text-slate-400">{children}</div>}
    </div>
  )
}

const SEVERITY_TONE = { high: 'rose', medium: 'amber', low: 'slate' }

export function LimitationItem({ item }) {
  return (
    <li className="border-t border-slate-800/70 py-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={SEVERITY_TONE[item.severity] || 'slate'}>{item.severity}</Badge>
        <p className="text-sm font-semibold text-slate-200">{item.title}</p>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-slate-400">{item.detail}</p>
    </li>
  )
}

/** Coverage banner. Amber or rose whenever the AI evaluation does not cover every case. */
export function CoverageBanner({ ai }) {
  const complete = ai.coverage_complete
  const tone = complete
    ? 'border-emerald-700/70 bg-emerald-950/30'
    : ai.evaluated === 0
      ? 'border-rose-800/70 bg-rose-950/30'
      : 'border-amber-700/70 bg-amber-950/30'
  return (
    <div className={`rounded-lg border px-4 py-3 ${tone}`} role="status">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          AI evaluation status
        </p>
        <p className="font-mono text-sm font-semibold text-slate-100">{ai.status}</p>
      </div>
      <p className="mt-1.5 font-mono text-sm text-slate-200">
        {ai.evaluated}/{ai.total} evaluated · {ai.remaining} remaining
      </p>
      <p className="mt-1 text-xs leading-relaxed text-slate-300/90">{ai.headline}</p>
    </div>
  )
}
