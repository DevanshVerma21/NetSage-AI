/**
 * The only module in the frontend that calls `fetch`.
 *
 * Two reasons it is centralised rather than convenient. First, error translation: the
 * backend answers the human gate with meaningful status codes (409 for "nobody reviewed
 * this", 422 for a malformed verdict), and every page needs the same readable message
 * rather than its own guess. Second, honesty: there is exactly one place to audit for what
 * this client is allowed to send, and no function here accepts a mutation, a CLI command,
 * or a device name. A fix is requested by naming a human approval — never by describing a
 * change.
 *
 * No credential is read, stored, or sent from the browser. The backend holds the only key.
 */

const BASE = '/api'

/** An HTTP failure carrying the status code, so a page can react to 409 specifically. */
export class ApiError extends Error {
  constructor(status, message, body) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

/** FastAPI's 422 body is a list of per-field errors; flatten it into one readable line. */
function readDetail(status, body) {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = (item.loc || []).filter((part) => part !== 'body').join('.')
        return field ? `${field}: ${item.msg}` : item.msg
      })
      .join('; ')
  }
  return `The server returned HTTP ${status}.`
}

async function request(path, { method = 'GET', body } = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    // Distinguished from an HTTP error on purpose: the usual cause is that the backend
    // is not running, and "check the server" is more useful than "request failed".
    throw new ApiError(
      0,
      'Could not reach the NetSage backend. Start it with ' +
        '`uvicorn backend.app.main:app --reload` and try again.',
    )
  }

  if (response.status === 204) return null

  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    throw new ApiError(response.status, readDetail(response.status, payload), payload)
  }
  return payload
}

function query(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && `${value}`.trim() !== '') {
      search.set(key, `${value}`.trim())
    }
  }
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

// --- meta ---------------------------------------------------------------------------------

export const getHealth = () => request('/health')

// --- case library -------------------------------------------------------------------------

export const getCases = (filters) => request(`/cases${query(filters)}`)
export const getCase = (caseId) => request(`/cases/${encodeURIComponent(caseId)}`)

// --- the deterministic engine -------------------------------------------------------------

/** Runs the rule engine only. The backend guarantees `ai_used === false` on this path. */
export const checkRules = (caseId) =>
  request('/rules/check', { method: 'POST', body: { case_id: caseId } })

// --- the AI proposal ----------------------------------------------------------------------

/**
 * Requests an AI diagnosis. The record comes back `awaiting_human_review` with
 * `applied: false`; there is no parameter here — or in the backend — that could change it.
 */
export const diagnose = (caseId, provider) =>
  request('/diagnose', { method: 'POST', body: { case_id: caseId, provider } })

export const getDiagnosis = (diagnosisId) =>
  request(`/diagnoses/${encodeURIComponent(diagnosisId)}`)
export const getDiagnoses = (filters) => request(`/diagnoses${query(filters)}`)

// --- the human gate -----------------------------------------------------------------------

/** Records the verdict server-side. Approval never lives in React state alone. */
export const createReview = (review) => request('/reviews', { method: 'POST', body: review })

export const getReview = (reviewId) => request(`/reviews/${encodeURIComponent(reviewId)}`)

// --- the simulated fix --------------------------------------------------------------------

/**
 * Applies the approved fix to a copy of the lab model. The request names a review and
 * nothing else — the mutations come from the reviewed diagnosis's own deterministic
 * findings, so this client cannot describe a configuration change of its own.
 */
export const applyFix = (reviewId) =>
  request('/fixes/apply', { method: 'POST', body: { review_id: reviewId } })

export const getFix = (runId) => request(`/fixes/${encodeURIComponent(runId)}`)

/** Fix runs for one diagnosis — used to show an already-applied result on revisit. */
export const getFixes = (filters) => request(`/fixes${query(filters)}`)
