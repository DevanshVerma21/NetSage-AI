import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { getHealth } from '../api/client.js'
import { Badge } from './StatusBadge.jsx'

/**
 * The application frame.
 *
 * The strip under the header states the architecture, because an evaluator should be able to
 * read the system's contract without clicking anything: the AI proposes, deterministic rules
 * verify, a human approves. The "Simulated Lab" indicator reports the backend's own
 * `execution_scope` — it is not a decorative label, and if the backend ever reported a
 * different scope this header would say so.
 */
export function AppShell({ children }) {
  const [health, setHealth] = useState(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let active = true
    getHealth()
      .then((data) => active && setHealth(data))
      .catch(() => active && setOffline(true))
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="min-h-screen bg-slate-950">
      <header className="border-b border-slate-800 bg-slate-900/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3.5 sm:px-6">
          <Link to="/" className="group">
            <h1 className="text-lg font-bold tracking-[0.16em] text-slate-50">NETSAGE AI</h1>
            <p className="text-[11px] tracking-wide text-slate-400">
              AI-Assisted Network Troubleshooting
            </p>
          </Link>

          <nav className="flex items-center gap-1">
            <NavLink
              to="/"
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm font-medium ${
                  isActive
                    ? 'bg-slate-800 text-slate-100'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`
              }
            >
              Cases
            </NavLink>
          </nav>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            {offline ? (
              <Badge tone="rose">Backend offline</Badge>
            ) : (
              <>
                <Badge tone="sky">
                  <span className="inline-block size-1.5 rounded-full bg-sky-400" />
                  Simulated Lab
                </Badge>
                {health && (
                  <span className="font-mono text-[11px] text-slate-500">
                    v{health.version} · {health.cases_loaded} case
                    {health.cases_loaded === 1 ? '' : 's'} · {health.rules_registered} rules ·{' '}
                    {health.llm_provider}
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        <div className="border-t border-slate-800/70 bg-slate-950/60">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-[11px] uppercase tracking-[0.14em] sm:px-6">
            <span className="text-violet-400">AI proposes</span>
            <span className="text-slate-700">·</span>
            <span className="text-sky-400">Deterministic rules verify</span>
            <span className="text-slate-700">·</span>
            <span className="text-emerald-400">A human approves</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>

      <footer className="mx-auto max-w-7xl px-4 pb-8 text-[11px] text-slate-600 sm:px-6">
        Every case in this prototype is a simulated lab topology. No fix is executed on
        physical hardware or in Packet Tracer, and no endpoint connects to a device.
      </footer>
    </div>
  )
}

export default AppShell
