/**
 * The captured `show` command evidence.
 *
 * Output is never truncated and never reflowed: this is the exact text the AI was given and
 * the exact text the evidence verifier searches, so a reviewer checking a citation by eye
 * has to be looking at the same bytes. Long output scrolls; it does not collapse.
 */
export function ShowOutputViewer({ outputs = [] }) {
  if (outputs.length === 0) {
    return <p className="text-sm text-slate-500">This case carries no show output.</p>
  }

  return (
    <div className="space-y-4">
      {outputs.map((entry, index) => (
        <article
          key={`${entry.device}-${entry.command}-${index}`}
          className="overflow-hidden rounded-md border border-slate-800 bg-slate-950/80"
        >
          <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-800 bg-slate-900/60 px-3 py-2">
            <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] font-semibold text-sky-300">
              {entry.device}
            </span>
            <span className="font-mono text-xs text-slate-300">{entry.command}</span>
          </header>
          <div className="max-h-96 overflow-auto px-3 py-2">
            <pre className="cisco-output">{entry.output}</pre>
          </div>
        </article>
      ))}
    </div>
  )
}

export default ShowOutputViewer
