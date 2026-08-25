/**
 * The Phase 4 acceptance test: CASE-001, end to end, through the running frontend.
 *
 * Deliberately not a browser-automation suite. Adding Playwright for one flow would mean a
 * large dependency and a driver download for a two-day prototype, and the spec asks for a
 * minimum verification rather than a frontend test suite. What this does instead is exercise
 * the real integration surface: it starts the FastAPI backend and the Vite dev server, then
 * drives the exact request sequence `src/api/client.js` makes — through Vite's `/api` proxy,
 * so the proxy configuration is under test too — and asserts that every route the router
 * declares is actually served.
 *
 * What it therefore proves: the API contract the components read, the proxy, the routes, the
 * human gate's 409s, and the verification payload. What it cannot prove is pixel rendering;
 * that is checked by hand against the same server.
 *
 * Records go to a temporary DATA_DIR so a test run never touches the repository's data/.
 */

import { spawn, spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const ROOT = resolve(import.meta.dirname, '..', '..')
const FRONTEND = resolve(import.meta.dirname, '..')

// Spare ports throughout, so a test run cannot collide with — or be answered by — a backend
// or dev server someone already has open on 8000/5173.
const BACKEND_PORT = 8021
const UI_PORT = 5174
// `localhost`, not `127.0.0.1`: Vite's dev server binds the hostname, which on Windows can
// mean the IPv6 loopback only, and a request to the dotted-quad address is then refused.
const API = `http://localhost:${UI_PORT}/api`
const UI = `http://localhost:${UI_PORT}`

const DISCLAIMER =
  'Verified against simulated lab model — not executed on physical hardware or Packet Tracer.'

let passed = 0
const failures = []

function check(label, condition, detail = '') {
  if (condition) {
    passed += 1
    console.log(`  PASS  ${label}`)
  } else {
    failures.push(label)
    console.log(`  FAIL  ${label}${detail ? ` — ${detail}` : ''}`)
  }
}

function step(name) {
  console.log(`\n${name}`)
}

async function call(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    method: options.method || 'GET',
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  return { status: response.status, body: payload }
}

async function waitFor(url, attempts = 90) {
  for (let index = 0; index < attempts; index += 1) {
    try {
      await fetch(url)
      return true
    } catch {
      await new Promise((done) => setTimeout(done, 500))
    }
  }
  return false
}

async function main() {
  // --- a throwaway DATA_DIR. cases.json lives there too, so it must be copied across. ---
  const dataDir = mkdtempSync(join(tmpdir(), 'netsage-e2e-'))
  for (const name of ['cases.json', 'cases.csv']) {
    const source = join(ROOT, 'data', name)
    if (existsSync(source)) copyFileSync(source, join(dataDir, name))
  }

  const logs = { backend: '', frontend: '' }
  function collect(child, key) {
    child.stdout?.on('data', (chunk) => (logs[key] += chunk))
    child.stderr?.on('data', (chunk) => (logs[key] += chunk))
  }

  // No `shell: true`, and Vite is started through its own bin rather than `npx`: both keep
  // the spawned pid the actual server, so the cleanup below can really kill it. Going through
  // cmd.exe or npx leaves a grandchild that survives, holding its port for the next run.
  const backend = spawn(
    process.platform === 'win32' ? 'python.exe' : 'python',
    ['-m', 'uvicorn', 'backend.app.main:app', '--port', String(BACKEND_PORT)],
    { cwd: ROOT, env: { ...process.env, DATA_DIR: dataDir }, stdio: 'pipe' },
  )
  const frontend = spawn(
    process.execPath,
    [join(FRONTEND, 'node_modules', 'vite', 'bin', 'vite.js'), '--port', String(UI_PORT), '--strictPort'],
    {
      cwd: FRONTEND,
      env: { ...process.env, NETSAGE_API_TARGET: `http://127.0.0.1:${BACKEND_PORT}` },
      stdio: 'pipe',
    },
  )
  collect(backend, 'backend')
  collect(frontend, 'frontend')

  try {
    if (!(await waitFor(`http://127.0.0.1:${BACKEND_PORT}/api/health`)))
      throw new Error(`the backend did not start:\n${logs.backend.slice(-800)}`)
    if (!(await waitFor(UI)))
      throw new Error(`the Vite dev server did not start:\n${logs.frontend.slice(-800)}`)

    // --- 1. the app shell's health call, through the proxy --------------------------------
    step('1. GET /api/health (through the Vite proxy)')
    const health = await call('/health')
    check('health returns 200 through the proxy', health.status === 200)
    check('execution_scope is simulated_lab_model', health.body?.execution_scope === 'simulated_lab_model')
    check('human_review_required is true', health.body?.human_review_required === true)
    check(
      'no credential in the health payload',
      !/api_key|AIza|sk-ant/i.test(JSON.stringify(health.body)),
    )

    // --- 2. the case library -------------------------------------------------------------
    step('2. GET /api/cases — Case Library')
    const cases = await call('/cases')
    check('cases returns 200', cases.status === 200)
    const caseSummary = (cases.body || []).find((item) => item.case_id === 'CASE-001')
    check('CASE-001 is immediately visible', Boolean(caseSummary))
    check(
      'the summary carries every column the table renders',
      Boolean(
        caseSummary?.title &&
          caseSummary?.concept_tag &&
          caseSummary?.severity &&
          caseSummary?.osi_layer,
      ),
    )
    const filtered = await call(`/cases?category=${caseSummary.concept_tag}&severity=${caseSummary.severity}`)
    check('the category and severity filters still return CASE-001',
      (filtered.body || []).some((item) => item.case_id === 'CASE-001'))
    const searched = await call('/cases?q=zzzz-no-such-case')
    check('an unmatched search returns an empty list', Array.isArray(searched.body) && searched.body.length === 0)

    // --- 3. the triage workbench's evidence ----------------------------------------------
    step('3. GET /api/cases/CASE-001 — Triage Workbench evidence')
    const detail = await call('/cases/CASE-001')
    check('the case loads', detail.status === 200)
    check('symptom and topology note are present', Boolean(detail.body?.symptom && detail.body?.topology_note))
    check('show outputs are present', (detail.body?.show_outputs || []).length > 0)
    check(
      'every show output carries device, command and text',
      detail.body.show_outputs.every((entry) => entry.device && entry.command && entry.output),
    )
    check('the case is labelled simulated-lab', detail.body?.source_label === 'simulated-lab')
    const missing = await call('/cases/CASE-404')
    check('an unknown case is a 404 the UI can report', missing.status === 404)

    // --- 4. the deterministic rule check -------------------------------------------------
    step('4. POST /api/rules/check — Deterministic Rule Engine')
    const rules = await call('/rules/check', { method: 'POST', body: { case_id: 'CASE-001' } })
    check('the checker returns 200', rules.status === 200)
    check('ai_used is false on this path', rules.body?.ai_used === false)
    check(
      'CASE-001 fires R004, R005 and R006',
      JSON.stringify(rules.body?.rule_ids) === JSON.stringify(['R004', 'R005', 'R006']),
      JSON.stringify(rules.body?.rule_ids),
    )
    check(
      'each finding carries what the card renders',
      rules.body.findings.every(
        (finding) =>
          finding.rule_id && finding.rule_name && finding.severity && finding.message,
      ),
    )

    // --- 5. the AI diagnosis -------------------------------------------------------------
    step('5. POST /api/diagnose — AI proposal (mock provider)')
    const created = await call('/diagnose', {
      method: 'POST',
      body: { case_id: 'CASE-001', provider: 'mock' },
    })
    const diagnosis = created.body
    check('the diagnosis is created (201)', created.status === 201)
    check('status is awaiting_human_review', diagnosis?.status === 'awaiting_human_review')
    check('applied is false', diagnosis?.applied === false)
    check('review_id is null', diagnosis?.review_id === null)
    check('a root cause is proposed', Boolean(diagnosis?.ai?.root_cause))
    check('evidence citations are present', (diagnosis?.ai?.evidence || []).length > 0)
    check(
      'each citation carries the three fields the UI shows',
      diagnosis.ai.evidence.every(
        (item) => item.source_command && item.excerpt && item.why_it_matters,
      ),
    )
    check('a next command is present', Boolean(diagnosis?.ai?.next_command))
    check('fix steps are present', (diagnosis?.ai?.fix_steps || []).length > 0)
    check('verification steps are present', (diagnosis?.ai?.verification_steps || []).length > 0)
    check(
      'model and effective confidence are both present and separate',
      Boolean(
        diagnosis?.confidence?.model_confidence && diagnosis?.confidence?.effective_confidence,
      ),
    )
    check('the evidence integrity verdict is stored', Boolean(diagnosis?.evidence_integrity?.status))
    check('the reconciliation verdict is stored', Boolean(diagnosis?.reconciliation?.status))
    check('the deterministic findings travel with the proposal',
      (diagnosis?.rule_findings || []).length > 0)
    check(
      'no credential in the diagnosis payload',
      !/api_key|AIza|sk-ant/i.test(JSON.stringify(diagnosis)),
    )

    // --- 6. the gate refuses a fix before any review -------------------------------------
    step('6. POST /api/fixes/apply with no review — the gate must refuse')
    const premature = await call('/fixes/apply', {
      method: 'POST',
      body: { diagnosis_id: diagnosis.diagnosis_id },
    })
    check('an unreviewed diagnosis is refused with 409', premature.status === 409, `got ${premature.status}`)
    check('the 409 carries a human-readable detail the UI can print',
      typeof premature.body?.detail === 'string' && premature.body.detail.length > 10)

    // --- 7. the human verdict ------------------------------------------------------------
    step('7. POST /api/reviews — verdict accepted')
    const reviewed = await call('/reviews', {
      method: 'POST',
      body: { diagnosis_id: diagnosis.diagnosis_id, verdict: 'accepted', reviewer: 'phase4-e2e' },
    })
    const review = reviewed.body
    check('the review is recorded (201)', reviewed.status === 201)
    check('the agreement record is computed', Boolean(review?.agreement))
    const afterReview = await call(`/diagnoses/${diagnosis.diagnosis_id}`)
    check('the diagnosis now reads accepted', afterReview.body?.status === 'accepted')
    check('approval alone does not set applied', afterReview.body?.applied === false)

    step('7b. the Fix & Verify page loads its records by review id')
    const fetchedReview = await call(`/reviews/${review.review_id}`)
    check('GET /api/reviews/{id} resolves', fetchedReview.status === 200)
    check('it names the diagnosis to load next',
      fetchedReview.body?.diagnosis_id === diagnosis.diagnosis_id)

    // --- 8. the simulated fix ------------------------------------------------------------
    step('8. POST /api/fixes/apply — simulated fix and verification')
    const applied = await call('/fixes/apply', {
      method: 'POST',
      body: { review_id: review.review_id },
    })
    const run = applied.body
    check('the fix run is created (201)', applied.status === 201)
    check('verification_result is verified', run?.verification_result === 'verified', run?.verification_result)
    check('findings before are reported', (run?.findings_before || []).length > 0)
    check('findings after is empty', (run?.findings_after || []).length === 0)
    check(
      'R004, R005 and R006 are resolved',
      JSON.stringify(run?.resolved_rule_ids) === JSON.stringify(['R004', 'R005', 'R006']),
      JSON.stringify(run?.resolved_rule_ids),
    )
    check('no new finding was introduced', (run?.new_rule_ids || []).length === 0)
    check('the mutation log is present', (run?.mutations || []).length > 0)
    check('execution_scope is simulated_lab_model', run?.execution_scope === 'simulated_lab_model')
    check('the disclaimer is stored verbatim', run?.disclaimer === DISCLAIMER, JSON.stringify(run?.disclaimer))
    const finalDiagnosis = await call(`/diagnoses/${diagnosis.diagnosis_id}`)
    check('the diagnosis is now applied', finalDiagnosis.body?.applied === true)

    step('9. re-applying the same review')
    const again = await call('/fixes/apply', { method: 'POST', body: { review_id: review.review_id } })
    check('a second apply is refused with 409', again.status === 409, `got ${again.status}`)

    step('10. the stored case was not mutated by the fix')
    const reread = await call('/cases/CASE-001')
    check(
      'GET /api/cases/CASE-001 is unchanged after the fix run',
      JSON.stringify(reread.body) === JSON.stringify(detail.body),
    )

    // --- 11. a rejected diagnosis cannot reach a fix -------------------------------------
    step('11. reject flow — a rejected diagnosis cannot reach a fix')
    const second = await call('/diagnose', {
      method: 'POST',
      body: { case_id: 'CASE-001', provider: 'mock' },
    })
    const bare = await call('/reviews', {
      method: 'POST',
      body: { diagnosis_id: second.body.diagnosis_id, verdict: 'rejected' },
    })
    check('a rejection with no reason code is refused with 422', bare.status === 422, `got ${bare.status}`)
    const noNotes = await call('/reviews', {
      method: 'POST',
      body: {
        diagnosis_id: second.body.diagnosis_id,
        verdict: 'rejected',
        reason_code: 'wrong_root_cause',
      },
    })
    check('a rejection with no notes is refused with 422', noNotes.status === 422, `got ${noNotes.status}`)
    const rejection = await call('/reviews', {
      method: 'POST',
      body: {
        diagnosis_id: second.body.diagnosis_id,
        verdict: 'rejected',
        reason_code: 'wrong_root_cause',
        notes: 'The VLAN is present on the peer switch; this is a trunk pruning issue.',
        reviewer: 'phase4-e2e',
      },
    })
    check('the rejection is recorded (201)', rejection.status === 201)
    check('the rejection records root-cause disagreement', rejection.body?.agreement?.root_cause === false)
    const refusedByVerdict = await call('/fixes/apply', {
      method: 'POST',
      body: { review_id: rejection.body.review_id },
    })
    check('applying a rejected diagnosis is refused with 409', refusedByVerdict.status === 409, `got ${refusedByVerdict.status}`)
    const refusedByDiagnosis = await call('/fixes/apply', {
      method: 'POST',
      body: { diagnosis_id: second.body.diagnosis_id },
    })
    check('the diagnosis_id route is refused too', refusedByDiagnosis.status === 409, `got ${refusedByDiagnosis.status}`)
    const stillUnapplied = await call(`/diagnoses/${second.body.diagnosis_id}`)
    check('the rejected diagnosis remains applied: false', stillUnapplied.body?.applied === false)

    step('12. edit flow — a correction is required, and narrows the fix')
    const third = await call('/diagnose', {
      method: 'POST',
      body: { case_id: 'CASE-001', provider: 'mock' },
    })
    const noReason = await call('/reviews', {
      method: 'POST',
      body: { diagnosis_id: third.body.diagnosis_id, verdict: 'edited' },
    })
    check('an edit with no reason code is refused with 422', noReason.status === 422, `got ${noReason.status}`)
    const noCorrection = await call('/reviews', {
      method: 'POST',
      body: {
        diagnosis_id: third.body.diagnosis_id,
        verdict: 'edited',
        reason_code: 'incomplete_root_cause',
      },
    })
    check('an edit with no correction is refused with 422', noCorrection.status === 422, `got ${noCorrection.status}`)
    const edited = await call('/reviews', {
      method: 'POST',
      body: {
        diagnosis_id: third.body.diagnosis_id,
        verdict: 'edited',
        reason_code: 'incomplete_root_cause',
        notes: 'Cause is right but the SVI shutdown is the primary fault.',
        corrected_root_cause: 'VLAN 30 is absent from SW1 and the Vlan30 SVI is shut down.',
        corrected_rule_ids: ['R005'],
        reviewer: 'phase4-e2e',
      },
    })
    check('the edited review is recorded (201)', edited.status === 201, JSON.stringify(edited.body).slice(0, 160))
    check('root-cause disagreement is recorded', edited.body?.agreement?.root_cause === false)
    const partial = await call('/fixes/apply', {
      method: 'POST',
      body: { review_id: edited.body.review_id },
    })
    check('the edited review permits a fix (201)', partial.status === 201, `got ${partial.status}`)
    check(
      'the fix was narrowed to the reviewer’s chosen finding',
      JSON.stringify([...new Set((partial.body?.mutations || []).map((m) => m.rule_id))]) ===
        JSON.stringify(['R005']),
      JSON.stringify((partial.body?.mutations || []).map((m) => m.rule_id)),
    )
    check(
      'a partial fix is reported as partial, not verified',
      partial.body?.verification_result === 'partial',
      partial.body?.verification_result,
    )
    check('the remaining findings are named', (partial.body?.remaining_rule_ids || []).length > 0)

    // --- 13. every declared route is served ----------------------------------------------
    step('13. the four routes are served by the app')
    for (const path of [
      '/',
      `/cases/CASE-001`,
      `/review/${diagnosis.diagnosis_id}`,
      `/fixes/${review.review_id}`,
    ]) {
      const response = await fetch(`${UI}${path}`)
      const html = await response.text()
      check(
        `${path} serves the app`,
        response.status === 200 && html.includes('/src/main.jsx'),
        `status ${response.status}`,
      )
    }

    console.log(`\n${'='.repeat(72)}`)
    console.log(`CASE-001 END-TO-END: ${failures.length === 0 ? 'PASS' : 'FAIL'}`)
    console.log(`${passed} checks passed, ${failures.length} failed`)
    if (failures.length > 0) {
      console.log('\nfailed checks:')
      for (const failure of failures) console.log(`  - ${failure}`)
    }
    return failures.length === 0 ? 0 : 1
  } finally {
    stop(backend)
    stop(frontend)
  }
}

// Synchronous on purpose: an async kill would still be queued when process.exit() runs, and
// the server would outlive the test and hold its port.
function stop(child) {
  if (!child.pid) return
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    child.kill()
  }
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(`\nE2E ABORTED: ${error.message}`)
    process.exit(1)
  })
