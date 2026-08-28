# NetSage AI

An AI-assisted troubleshooting helper for Cisco-style Packet Tracer / lab networks.

> **Engineering principle: AI proposes. Deterministic rules verify. Human approves.**
>
> The AI never applies a network fix. Every diagnosis is stored as
> `awaiting_human_review` with `applied: false`, and no fix can be simulated without a
> recorded human verdict.

| Document | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The pipeline, stage by stage, and why the deterministic half is independent of the AI half |
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | What has actually been measured, and what has not |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Every known limitation, stated plainly |
| [`docs/PLAN.md`](docs/PLAN.md) | The approved phase plan |

---

## Project overview

NetSage AI takes a captured network fault — a topology, the device `show` output, and a
statement of what the network is *supposed* to permit — and produces a reviewable
diagnosis:

1. A **deterministic rule engine** (pure Python, 15 rules, no model involved) reports what
   it can prove from the structured lab state.
2. A **language model** reads the raw `show` text and proposes a root cause with citations.
3. Three deterministic checks then run *on the model's answer*: every citation is
   substring-matched against the real output, the answer is reconciled against the rule
   findings, and the model's own confidence is capped by what survived checking.
4. A **human reviewer** accepts, edits or rejects. Nothing proceeds without that verdict.
5. An approved fix is **simulated** against a copy of the lab model and verified by
   re-running the rule engine. No device is ever touched.

The two halves are reported separately and never merged into a single score. The
deterministic results are validated; the live AI evaluation is currently incomplete, and the
product says so on its own dashboard rather than in a footnote.

## The problem

Lab and Packet Tracer networks fail for a small number of well-understood reasons — a VLAN
that was never created, an SVI left shut down, a gateway outside its own subnet, an ACL that
denies a flow the design intends to permit. Diagnosing them is slow for a learner and
repetitive for an instructor, but handing the job to a language model alone is worse than
slow: a model will produce a fluent root cause with invented evidence and no way for the
reader to tell the difference.

So the problem this prototype addresses is not "can a model diagnose a network fault". It is
**how a model's diagnosis can be made checkable** — and how the system can refuse to
overstate itself when the checks do not pass.

---

## Architecture

```
Input case (data/cases.json)
   ↓
LabState                      structured devices, interfaces, VLANs, routes, ACLs, flows
   ↓
Deterministic rule engine     15 pure functions · no AI · no I/O
   ↓
AI diagnosis                  Gemini or the offline mock, over the raw show text
   ↓
Evidence verifier             every citation matched against the real output
   ↓
Reconciler                    AI vs rules → agree · partial · ai_only · rules_only · conflict
   ↓
Confidence capping            the model's confidence is an input, never the output
   ↓
Human review                  accepted · edited · rejected — server-enforced, mandatory
   ↓
Simulated fix                 mutates a COPY of the lab model
   ↓
Verification                  the rule engine re-run; before/after finding diff
   ↓
Audit / evaluation            diagnoses · reviews · fix runs · evaluation records
```

The rule engine never sees the model's answer, and the verifier, reconciler and capping table
contain no model call. That is what makes the deterministic result usable as a check on the
AI result rather than a second opinion produced by the same machinery. Full detail:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Technology stack

| Layer | Choice | Note |
|---|---|---|
| Backend | Python 3.11+ (developed on 3.13), FastAPI, Pydantic v2, Uvicorn | Pydantic models are the schema contract for both storage and the AI response |
| Storage | Atomic JSON files under `data/` | No database. The dataset is small, versioned, and reviewable in a diff |
| AI provider | `google-genai`, model `gemini-3.6-flash` | Behind an `LLMProvider` protocol; a `mock` provider runs the whole app offline |
| Frontend | React 19, react-router-dom 7, Vite 8, Tailwind CSS 4 (`@tailwindcss/vite`) | No UI component library |
| Tests | pytest (540 offline tests), a Node end-to-end script | `pytest` never touches the network by default |

---

## Setup

Requires **Python 3.11+** and **Node 20+**. Everything except a live Gemini call runs
offline with no API key.

```bash
git clone <this repository>
cd "NetSage AI"

# backend
pip install -r backend/requirements.txt

# frontend
cd frontend && npm install && cd ..

# configuration (optional — the app runs without a key on LLM_PROVIDER=mock)
cp .env.example .env
```

## Environment variables

Copy [`.env.example`](.env.example) to `.env` and fill in what you need. `.env` is
gitignored and is not tracked in the repository.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` (live) · `mock` (offline, no key, deterministic) · `anthropic` (declared stub, never routes traffic) |
| `LLM_MODEL` | `gemini-3.6-flash` | Gemini Flash model. See the note below |
| `GEMINI_API_KEY` | — | Free key from <https://aistudio.google.com/apikey> |
| `ANTHROPIC_API_KEY` | — | Unused; the Anthropic provider is a stub |
| `DATA_DIR` | `data` | Where cases and records are read and written |
| `PROMPTS_DIR` | `prompts` | Where versioned prompts and the hash registry live |

No key is hard-coded, logged, echoed into an exception message, committed, or returned to
the frontend. `GET /api/health` reports `provider_configured: true|false` and never the
value. A test asserts that no endpoint's response body contains `api_key`, `sk-`, or `AIza`.

**On the model choice.** Verified against the live API on 2026-08-25: `gemini-3.6-flash`,
`gemini-3.5-flash` and `gemini-3.5-flash-lite` all work. `gemini-3.7-flash` is newer but
currently returns a persistent `503 "experiencing high demand"` on the free tier, so it is
not the default — switch with one line in `.env` when capacity returns. `gemini-2.0-flash`
is **shut down**.

With `LLM_PROVIDER=mock` the whole prototype runs with no key at all, and every record is
stamped `provider: "mock"` so a mock answer can never be mistaken for a real model answer.

## Backend startup

```bash
# from the repository root
uvicorn backend.app.main:app --reload
```

- API: <http://127.0.0.1:8000/api/health>
- Interactive docs: <http://127.0.0.1:8000/docs>

Useful offline entry points that need no key and no server:

```bash
python -m backend.app.rules.cli --list-rules            # the 15-rule catalogue
python -m backend.app.rules.cli --case CASE-001         # run the engine on one case
python -m backend.app.rules.cli --all --check-expected  # the golden expected-vs-fired check
python -m backend.scripts.phase2_demo                   # the full pipeline via the mock provider
python -m backend.scripts.verify_evaluation_integrity   # assert the dashboard matches the files
python scripts/smoke_api.py                             # prove the review gate over HTTP
```

## Frontend startup

```bash
cd frontend
npm run dev      # http://127.0.0.1:5173
npm run build    # production bundle into frontend/dist
npm run preview  # serve the built bundle
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser never holds an
absolute backend URL and there is no per-machine configuration. Start the backend first.
`NETSAGE_API_TARGET` overrides the proxy target for the end-to-end script only; it is read at
config time and never bundled.

Routes: `/` (Dashboard) · `/cases` · `/cases/:caseId` (Triage Workbench) · `/review` (genuine review queue) · `/review/:diagnosisId` ·
`/fixes/:reviewId` · `/responsible-ai`.

## Testing

```bash
python -m pytest -v          # 540 passed, 9 deselected
cd frontend && npm run build # production build must succeed
cd frontend && npm run e2e   # 89 checks, end to end over HTTP
```

The 9 deselected tests are the live-provider tests, excluded by the `-m 'not live'` default
in [`pyproject.toml`](pyproject.toml) so **an ordinary `pytest` run never calls Gemini**. Run
them deliberately with `python -m pytest -m live`; they skip cleanly with no key.

`npm run e2e` is not browser automation. It starts a real FastAPI process on a spare port
against a temporary `DATA_DIR`, starts Vite on 5174, and drives the same request sequence the
UI's own API client makes — case load, rule check, diagnosis, review, fix simulation,
verification, and the two read-only aggregate endpoints — asserting the review gate and the
simulated-execution scope at each step.

---

## The 40-case dataset

[`data/cases.json`](data/cases.json) is the single source of truth;
[`data/cases.csv`](data/cases.csv) is generated from it by
`python -m backend.scripts.export_cases_csv` and a test fails if the two drift apart.

Every case is **self-authored and simulated**. All 40 carry
`source_label: "simulated-lab"`, and a test asserts it — no case claims to have come from
real hardware or from an executed Packet Tracer session.

| Dimension | Composition |
|---|---|
| Concept tag | GATEWAY 5 · VLAN 5 · ROUTING 5 · DHCP 5 · ACL 4 · DNS 4 · NAT 4 · WIRELESS 4 · INTERFACE_CONFIG 4 |
| Severity | Critical 8 · High 30 · Medium 2 |
| OSI layer | L1 2 · L2 8 · L3 22 · L4 4 · L7 4 |
| Security-relevant | 5 of 40 |
| Compound faults | 8 cases declare more than one expected rule |

Each case declares its own ground truth: `expected_fault`, `expected_rule_ids`,
`expected_root_cause_keywords` and `expected_fix_steps`. **Ground truth is written when the
case is authored and is never edited after seeing a model's answer** — that is the property
that makes the evaluation meaningful, and it is stated here because it is a discipline, not a
mechanism.

Cases also declare `intended_flows`:

```json
{ "src": "PC-HR", "dst": "SRV-FILES", "proto": "tcp", "port": 445, "expect": "permit" }
```

You cannot decide whether a missing route or an ACL entry is a *fault* without knowing what
the network is supposed to do. Declaring intent turns "does this look wrong?" into a decidable
question, which is what lets R006, R012 and R013 be deterministic rather than a matter of
opinion.

Three tests keep the dataset honest:

- **[`tests/test_golden_expected_faults.py`](tests/test_golden_expected_faults.py)** — the
  engine must fire **exactly** each case's `expected_rule_ids`: no misses, no spurious extras.
  It validates the engine and the dataset in both directions at once.
- **`test_show_output_consistency.py`** — every fact in `lab_state` must be visible in the
  Cisco `show` text. The engine reasons over the structured state while the AI reasons over
  the text; if those drift, the AI would be asked to diagnose a fault it cannot see.
- **`test_cases_csv_sync.py`** — the generated CSV deliverable must match `cases.json`.

## The 15 deterministic rules

Rules are **pure functions** over a structured `LabState` — no I/O, no AI, no globals, no
mutation of the state they are given. That is what makes each one testable from a ten-line
fixture, and it is why the engine's output can serve as an independent check on the model.

Each rule has positive tests (the fault is detected) **and** negative tests (no false positive
on a healthy topology). Catalogue: `python -m backend.app.rules.cli --list-rules`.

The six the company document names explicitly are **mandatory** and were completed before any
optional rule was written:

| ID | Check | Sev / Layer | What it detects |
|---|---|---|---|
| **R001** | Duplicate IP address | Critical / L3 | The same IPv4 address on more than one interface or host — host↔host, host↔SVI, three-way |
| **R002** | Wrong subnet mask | High / L3 | A non-contiguous netmask, or a host whose mask disagrees with its own gateway's |
| **R003** | Gateway mismatch | High / L3 | A default gateway outside the host's subnet, owned by no L3 interface, or absent |
| **R004** | Interface down | High / L1 | A significant interface administratively down or line-protocol down; unused spare ports are ignored |
| **R005** | Missing VLAN | High / L2 | A VLAN referenced by a host, access port or SVI but absent from the VLAN database |
| **R006** | Missing route | High / L3 | No connected/static/dynamic/default route covering an intended flow's destination, or `ip routing` disabled |

The nine **optional** rules extend coverage to the rest of the dataset's fault space:

| ID | Check | Sev / Layer | What it detects |
|---|---|---|---|
| R007 | Access VLAN mismatch | High / L2 | An access port in a different VLAN from its segment — the port comes up, so it looks like a routing problem |
| R008 | Trunk / native VLAN mismatch | High / L2 | A trunk not carrying a required VLAN, or the two ends disagreeing about the native VLAN |
| R009 | Overlapping subnets | High / L3 | Two L3 interfaces with overlapping address space, so one connected route swallows the other's traffic |
| R010 | DHCP configuration fault | High / L3 | A pool that mismatches its subnet, hands out an unusable gateway or DNS, excludes foreign addresses, or a client segment with no pool and no relay |
| R011 | DNS configuration / reachability fault | High / L7 | No resolver, the wrong resolver, a resolver nothing owns, or an unreachable resolver |
| R012 | ACL blocks intended flow | High / L4 | An ACL denying traffic the design permits, or permitting traffic it denies |
| R013 | NAT configuration fault | High / L3 | No inside/outside designation, a rule referencing something absent, or a dynamic rule with no global pool |
| R014 | Wireless guest isolation / SSID fault | High / L2 | Guest traffic not isolated as declared, a client on an undefined SSID, a shared guest VLAN, or an AP uplink down |
| R015 | SVI shutdown or missing | High / L3 | A populated VLAN with no usable gateway: its SVI is down, or was never created |

Every rule also carries the `show` commands that confirm it, so a finding tells a reader how
to check it rather than only what it concluded.

---

## AI architecture

```
DiagnoseRequest ─► Provider ─► AIDiagnosis ─► Evidence Verifier ─► Reconciler ─► Capping
   (5 sections)  (gemini/mock)   (schema)      (deterministic)     (deterministic)
                                                     │                 │           │
                                                     └─────────────────┴───────────┘
                                                   status = awaiting_human_review
                                                           applied = false
```

The model receives the case symptom, the topology note, the intended flows, the full
untruncated `show` output, and the deterministic findings. It returns a structured
`AIDiagnosis` — root cause, OSI layer, category, citations, fix steps, confidence, and an
explicit `insufficient_evidence` flag. If the evidence does not support a conclusion the
prompt requires the model to say so and name the next command to run, rather than guess.

**Prompt library.** Every prompt is versioned and hash-pinned:

| File | Role |
|---|---|
| [`prompts/diagnose_prompt.md`](prompts/diagnose_prompt.md) | primary prompt; hard constraints plus three worked examples |
| [`prompts/system_guardrails.md`](prompts/system_guardrails.md) | shared safety preamble, prepended to every call |
| [`prompts/fix_plan_prompt.md`](prompts/fix_plan_prompt.md) | approved root cause → ordered Cisco CLI plus verification |
| [`prompts/registry.json`](prompts/registry.json) | name → version → SHA-256, stamped onto every diagnosis |

`load_prompt` **refuses** to load a prompt whose SHA-256 disagrees with the registry, so a
forgotten `python -m backend.scripts.update_prompt_registry` fails loudly instead of stamping
records with a stale identity. Hashes are computed with line endings normalised, so a Windows
and a Linux checkout of the same commit agree. Current versions: `diagnose_prompt` **1.2.1**,
`system_guardrails` 1.1.0, `fix_plan_prompt` 1.0.0.

The three worked examples teach three distinct behaviours: evidence-gated confidence, a
confident diagnosis when the evidence is decisive, and declining to guess.

**Provider abstraction.**

| Provider | Role |
|---|---|
| `gemini` | default live provider — `google-genai`, native structured output, exponential backoff on transient 429/5xx |
| `mock` | deterministic, offline, zero-key; derives its diagnosis from the rule findings and quotes real lines from the supplied output |
| `anthropic` | declared stub — `is_available()` is `False`, so the factory can never route real traffic into an unimplemented path |

A test asserts that **no module outside `backend/app/ai/gemini_provider.py` imports the Gemini
SDK**, so the abstraction is enforced rather than merely intended. Without a key the factory
falls back to mock *and says so* in a warning attached to the result.

## Evidence verification

Every citation the model produces names a `source_command` and quotes an `excerpt`. The
verifier — [`backend/app/ai/evidence_verifier.py`](backend/app/ai/evidence_verifier.py),
pure Python, no model — requires that excerpt to actually appear in the output of that
command for that case.

- Whitespace and case are normalised (`re.sub(r"\s+", " ", text).strip().lower()`), so a
  reflowed or re-cased line is still a real citation.
- Fabrication is not forgiven. Failure reasons are recorded explicitly:
  `excerpt_not_found`, `unknown_source_command`, `empty_excerpt`.
- A failed citation is **shown to the reviewer**, never silently dropped.
- Verdicts: `passed` · `partial` · `failed`.

The verifier is deliberately treated as fixed: when a prompt version produced unverifiable
citations, the prompt was corrected, not the verifier.

## Confidence capping

The model's confidence is an **input**, never the output. Ceilings compose, and the lowest
wins:

| Condition | Ceiling |
|---|---|
| evidence verification `failed` | **LOW** |
| AI / rule `conflict` | MEDIUM |
| `insufficient_evidence = true` | MEDIUM |
| `ai_only` — nothing corroborates it | MEDIUM |
| HIGH claimed with fewer than 2 verified citations | MEDIUM |
| otherwise | the model's value is preserved |

`model_confidence` and `effective_confidence` are stored **separately**, so a reviewer can
always see the gap between what the AI claimed and what survived checking.

The **reconciler** produces the input to two of those rows by comparing the AI's answer with
the deterministic findings: `agree` · `partial` · `ai_only` · `rules_only` · `conflict`.

## Human review

Mandatory, and enforced by the backend from stored records — not by the interface.

| Situation | Result |
|---|---|
| Apply with no review at all | **409** |
| Apply a **rejected** diagnosis | **409** |
| Apply the same diagnosis twice | **409** |
| Review the same diagnosis twice | **409** — the audit trail is not overwritten |
| `edited` with no reason code or no correction | **422** |
| `rejected` with no reason code or no notes | **422** |
| A request containing a mutation, command, or device | **422** — no request model has such a field |

A verdict is one of `accepted` · `edited` · `rejected`, recorded through `POST /api/reviews`
with a reason code, and stored permanently. The Triage Workbench shows no fix control at all
until a verdict exists.

## Simulated execution

There is **no device connectivity anywhere in this codebase**. No SSH, no Telnet, no Netmiko,
no paramiko, no scrapli, no `subprocess`, no shell execution. A sweep for all of those is part
of the hardening checklist and returns nothing but a disclaimer comment.

An approved "fix" does exactly this: it deep-copies the structured `LabState`, applies the
mutations *derived from the reviewed diagnosis's own deterministic findings*, and re-runs the
rule engine over the copy. The result reports which findings were resolved, which remain, and
which appeared.

- `POST /api/fixes/apply` accepts a `review_id` (or a `diagnosis_id` whose review the server
  looks up itself) **and nothing else**. A client cannot describe a change it wants made.
- Every fix run carries `execution_scope: "simulated_lab_model"`.
- Every verification carries the disclaimer verbatim: *"Verified against simulated lab model —
  not executed on physical hardware or Packet Tracer."*

Nothing in this system has ever executed a command on a device, and no record claims otherwise.

## Responsible AI

`/responsible-ai` in the UI and `GET /api/responsible-ai` expose, from stored data only: the
evaluation coverage and status, the methodology, the grading scheme, the evidence-verification
statuses, the confidence-capping triggers, the prompt versions with their hashes, the human
gate, the execution scope (what the system can and cannot do), the correction log, and the
known limitations ranked by severity.

Two properties are structural rather than editorial:

- **No metric is hard-coded.** Every figure is recomputed from `data/cases.json`, the rule
  registry, `data/evaluation_results.json` and the review store on each request. Pointing
  `DATA_DIR` at an empty directory produces zeros, and a test asserts that.
- **Accuracy is withheld until coverage is complete.** `accuracy` is `null` — the dashboard
  renders the literal word *withheld* — unless every case in the dataset has an official
  evaluation record. Invalidated records and failed provider calls count as **not evaluated**
  and cannot enter the denominator.

`python -m backend.scripts.verify_evaluation_integrity` recomputes every dashboard figure
straight from the files on disk and asserts field-by-field equality, so "the dashboard matches
the backend data" is a checked claim. Currently 33/33 checks pass.

Human review has **10 recorded reviews**: 5 accepted, 2 edited and 3 rejected. The stored
Responsible AI log contains **5 genuine corrections**.

---

## Current Gemini evaluation limitation

**Live Gemini evaluation is currently incomplete because only 20 of the 40 cases were
authorized and evaluated in this run.**

Official Gemini evaluation coverage: **22/40 cases.** All official records use Gemini
`gemini-3.6-flash`, `diagnose_prompt` v1.2.1, and the registered prompt hash. Accuracy is
withheld because 20 cases remain unevaluated.

What is actually on disk:

| Record set | State |
|---|---|
| `evaluation_results.prompt-1.0.0.archive.json` | 27 records from an earlier prompt version, **retained** for auditability |
| `evaluation_results.prompt-1.2.0.invalidated.archive.json` | the superseded CASE-001 record, retained exactly for auditability |
| `evaluation_results.json` | 22 official v1.2.1 Gemini results and one retained CASE-005 quota failure |
| Official result outcomes | 3 CORRECT, 19 PARTIAL, 0 INCORRECT |
| Evidence integrity | 4 passed, 18 failed |

The remaining 18 cases are unevaluated because Gemini quota was exhausted after the authorized
continuation began. The quota failure remains retained in the active results file.

What was deliberately *not* done: no result was fabricated or synthesised, no invalidated or
failed record was promoted to official, no archived history was deleted, and no accuracy was
computed from partial coverage. The dashboard reports status
`PARTIAL — Gemini quota limited` and withholds accuracy, which is the truth.

**The demo does not depend on Gemini.** With `LLM_PROVIDER=mock` the full path — case →
rules → AI proposal → evidence verification → reconciliation → capping → human review →
simulated fix → verification — runs offline and deterministically. The deterministic half is
fully validated independently of any model: 40 cases, 15 rules, golden expected-vs-fired
**PASS**, rule pass rate **1.0**.

See [`docs/EVALUATION.md`](docs/EVALUATION.md) for the methodology and
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) for the complete list.

---

## API surface

Every route is under `/api`. No endpoint connects to a device, accepts a configuration change
from the client, or returns a credential.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Version, cases loaded, rules registered, execution scope, whether a provider is configured (never the key) |
| GET | `/api/cases` | Case summaries; filters `category`, `severity`, `osi_layer`, `q` |
| GET | `/api/cases/{case_id}` | One full case, including its show outputs |
| POST | `/api/rules/check` | The deterministic engine only. `ai_used` is always `false` |
| POST | `/api/diagnose` | Run the AI pipeline; persists as `awaiting_human_review`, `applied=false` |
| GET | `/api/diagnoses` · `/api/diagnoses/{id}` | Stored proposals with every independent check |
| POST | `/api/reviews` | Record a human verdict: accepted · edited · rejected |
| GET | `/api/reviews` · `/api/reviews/{id}` | The audit trail |
| POST | `/api/fixes/apply` | Simulate an **approved** fix against a copy of the lab model |
| GET | `/api/fixes` · `/api/fixes/{run_id}` | Fix runs with before/after verification |
| GET | `/api/dashboard` | Deterministic and AI figures, calculated per request, kept apart |
| GET | `/api/responsible-ai` | Methodology, execution scope, correction log, limitations |
| GET | `/api/evaluations` | Stored evaluation records; filter `case_id` |

Records are written to `data/diagnoses.json`, `data/reviews.json` and `data/fix_runs.json`
(atomic writes, missing files tolerated). Those three are gitignored: they are per-run output,
not source.

## Project layout

```
backend/
  app/
    config.py              settings from .env (no hard-coded keys)
    netutils.py            pure IPv4 helpers (total functions, never raise)
    store.py               atomic JSON persistence, no database
    api/router.py          every HTTP route
    models/                enums · lab_state · case · diagnosis · records
    rules/
      engine.py            @rule registry, Finding model, runner
      checks/              ip_addressing · gateway · interface · vlan · routing
                           dhcp · dns · acl · nat · wireless
      cli.py               the deliverable rule checker
    ai/
      base.py              LLMProvider protocol · DiagnoseRequest · ProviderResult
      factory.py           provider selection + no-key fallback
      gemini_provider.py   the only Gemini import in the codebase
      mock_provider.py     deterministic offline provider
      schema_utils.py      Pydantic → Gemini wire-schema conversion
      prompt_loader.py     versioned prompt loading + hash enforcement
      evidence_verifier.py deterministic citation checking
      reconciler.py        AI vs rules, five states
      confidence.py        the capping table
    services/              case_repo · diagnose · review_service · fix_simulator
                           evaluation · dashboard
  scripts/                 export_cases_csv · update_prompt_registry · phase2_demo
                           live_diagnose_demo · review_candidates
                           verify_evaluation_integrity
frontend/
  src/pages/               Dashboard · CaseLibrary · TriageWorkbench
                           HumanReview · FixVerify · ResponsibleAI
  src/components/          Panel/Badge/ui · Metrics · CaseEvaluation
                           RuleFindingCard · AIDiagnosisCard · ShowOutputViewer
  scripts/e2e_case001.mjs  the end-to-end acceptance script
data/                      cases.json (source of truth) · cases.csv (generated)
                           evaluation_results.json + the v1.0.0 archive
prompts/                   diagnose_prompt · system_guardrails · fix_plan_prompt · registry.json
docs/                      ARCHITECTURE · EVALUATION · LIMITATIONS · PLAN
reports/                   rule-checker output · test run · pipeline demo
                           live Gemini smoke test · evaluation report · coverage matrix
tests/                     549 tests (540 selected offline + 9 live, deselected by default)
```

## Honesty commitments

Enforced in code and in tests, not just documented:

1. **No fix is ever auto-applied.** No code path exists that can push configuration to a
   device. A "fix" mutates a *copy* of the structured `LabState`; verification re-runs the
   deterministic engine and reports the before/after finding diff.
2. **Every verification states its scope**, verbatim: *"Verified against simulated lab model —
   not executed on physical hardware or Packet Tracer."*
3. **No fabricated Packet Tracer execution.** Every case carries
   `source_label: "simulated-lab"` and a test asserts it.
4. **AI evidence is checked, not trusted.** Every citation is matched against the supplied
   show output; an unverifiable citation caps confidence at LOW and raises a warning rather
   than being quietly accepted.
5. **Human review is mandatory and server-enforced**, not a UI convention.
6. **No dashboard number is hard-coded.** Every figure is recomputed from stored data on each
   request, and an integrity script asserts the dashboard equals the files.
7. **Incomplete evaluation is reported as incomplete.** Accuracy is withheld until coverage is
   complete; failed and invalidated records are retained and counted as not evaluated.
8. **No key is committed, logged, or returned.** `.env` is gitignored and untracked, and a test
   asserts no endpoint body contains a credential.
