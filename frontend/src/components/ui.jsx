/**
 * Small shared primitives. Kept in one file rather than one file each: they are a handful
 * of lines apiece and splitting them would add navigation cost without adding structure.
 */

/** A titled panel. `tone` marks a section as deterministic, AI-proposed, or a warning. */
export function Panel({ title, subtitle, label, tone = 'default', right, children }) {
  const tones = {
    default: 'border-slate-800 bg-slate-900/40',
    deterministic: 'border-sky-900/70 bg-sky-950/20',
    ai: 'border-violet-900/70 bg-violet-950/20',
    warn: 'border-amber-700/70 bg-amber-950/25',
    danger: 'border-rose-800/70 bg-rose-950/25',
  }
  return (
    <section className={`rounded-lg border ${tones[tone] || tones.default}`}>
      {(title || label || right) && (
        <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-800/80 px-4 py-3">
          <div>
            {label && (
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                {label}
              </p>
            )}
            {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="px-4 py-4">{children}</div>
    </section>
  )
}

export function Button({ variant = 'primary', busy = false, children, ...rest }) {
  const variants = {
    primary: 'bg-sky-600 hover:bg-sky-500 text-white border-sky-500',
    accept: 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500',
    edit: 'bg-amber-600 hover:bg-amber-500 text-white border-amber-500',
    reject: 'bg-rose-700 hover:bg-rose-600 text-white border-rose-600',
    ghost: 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700',
  }
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={`rounded-md border px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
        variants[variant] || variants.primary
      } ${rest.className || ''}`}
    >
      {busy ? 'Working…' : children}
    </button>
  )
}

/** A plain textual loading state. No animation beyond a pulsing dot. */
export function Loading({ label = 'Loading…' }) {
  return (
    <p className="flex items-center gap-2 py-6 text-sm text-slate-400">
      <span className="inline-block size-2 animate-pulse rounded-full bg-sky-400" />
      {label}
    </p>
  )
}

/**
 * A readable error. `ApiError.status` is shown because the code is meaningful in this
 * system — a 409 is the human gate refusing, not a bug — but no stack trace ever is.
 */
export function ErrorNotice({ error, className = '' }) {
  if (!error) return null
  const status = error.status
  const heading =
    status === 409
      ? 'Refused by the human review gate (HTTP 409)'
      : status === 422
        ? 'The request was not valid (HTTP 422)'
        : status === 404
          ? 'Not found (HTTP 404)'
          : status === 0
            ? 'Backend unreachable'
            : status >= 500
              ? `Server error (HTTP ${status})`
              : `Request failed${status ? ` (HTTP ${status})` : ''}`

  return (
    <div
      role="alert"
      className={`rounded-md border border-rose-800/70 bg-rose-950/40 px-4 py-3 ${className}`}
    >
      <p className="text-sm font-semibold text-rose-200">{heading}</p>
      <p className="mt-1 text-sm text-rose-100/85">{error.message}</p>
    </div>
  )
}

export function Field({ label, hint, required = false, children }) {
  return (
    <label className="block">
      <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        {label}
        {required && <span className="ml-1 text-rose-400">*</span>}
      </span>
      <div className="mt-1.5">{children}</div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm ' +
  'text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none'

/** A label / value row, used for the dense metadata grids. */
export function Meta({ label, children, className = '' }) {
  return (
    <div className={className}>
      <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
        {label}
      </p>
      <div className="mt-1 text-sm text-slate-200">{children}</div>
    </div>
  )
}
