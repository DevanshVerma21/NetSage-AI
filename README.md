# NetSage AI

An AI-assisted troubleshooting helper for Cisco-style Packet Tracer / lab networks.

> **Engineering principle: AI proposes. Deterministic rules verify. Human approves.**
>
> The AI never applies a network fix. Every diagnosis starts as
> `awaiting_human_review`, and no fix can be applied without a recorded human verdict.

Company problem statement: [`AI_Problem Statement.docx`](AI_Problem%20Statement.docx)
Approved architecture: [`docs/PLAN.md`](docs/PLAN.md)

---

## Build status

| Phase | Scope | Status |
|---|---|:--:|
| **1** | Foundation · six mandatory rules (R001–R006) fully tested · representative case · rule-checker CLI | ✅ **complete** |
| **2** | AI layer: prompts · provider abstraction · Gemini · mock · evidence verifier · reconciler · confidence capping | ✅ **complete** |
| **3** | API · server-enforced review gate · Fix Simulator · deterministic before/after verification | ✅ **complete** |
| 4 | Frontend vertical slice, CASE-001 proven end to end | ⏳ next |
| 5 | Expand to 40 cases · optional rules R007–R015 | — |
| 6 | Dashboard · Responsible AI log from a live batch run | — |
| 7 | Deliverables · docs · demo script | — |

**Phase 3 test result: 335 passed, 2 skipped, 9 deselected** offline. The 2 skips are
deliberate Phase 5 dataset gates; the 9 deselected are the live provider tests, excluded by
default so `pytest` never touches the network.
Full log: [`reports/test_run.txt`](reports/test_run.txt).

---

## Quick start

Requires Python 3.11+. Everything in Phase 1 runs offline with no API key.

```bash
# 1. Install backend dependencies
pip install -r backend/requirements.txt

# 2. Run the test suite (fully offline — no key, no network)
python -m pytest tests -q

# 3. Run the deterministic rule checker (no AI, no network)
python -m backend.app.rules.cli --list-rules
python -m backend.app.rules.cli --case CASE-001
python -m backend.app.rules.cli --all --check-expected

# 4. Run the AI pipeline offline through the mock provider
python -m backend.scripts.phase2_demo

# 5. Run one live Gemini diagnosis (skips cleanly with no key)
python -m backend.scripts.live_diagnose_demo CASE-001

# 6. Regenerate deliverables after editing the dataset or a prompt
python -m backend.scripts.export_cases_csv
python -m backend.scripts.update_prompt_registry

# 7. Run the API (Phase 3) — http://127.0.0.1:8000/docs
uvicorn backend.app.main:app --reload

# 8. Prove the whole gate end to end over HTTP (mock provider, temp storage)
python scripts/smoke_api.py
```

### API (Phase 3)

Every route is under `/api`. Nothing in this surface connects to a device: there is no SSH,
Telnet, Netmiko, or command execution anywhere in the codebase, and no endpoint accepts a
configuration change from the client.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Version, cases loaded, rules registered, whether a provider is configured (never the key) |
| GET | `/api/cases` | Case summaries; filters `category`, `severity`, `osi_layer`, `q` |
| GET | `/api/cases/{case_id}` | One full case, including its show outputs |
| POST | `/api/rules/check` | The deterministic engine only. `ai_used` is always `false` |
| POST | `/api/diagnose` | Run the AI pipeline; persists as `awaiting_human_review`, `applied=false` |
| GET | `/api/diagnoses` · `/api/diagnoses/{id}` | Stored proposals with every independent check |
| POST | `/api/reviews` | Record a human verdict: accepted · edited · rejected |
| GET | `/api/reviews` · `/api/reviews/{id}` | The audit trail |
| POST | `/api/fixes/apply` | Simulate an **approved** fix against a copy of the lab model |
| GET | `/api/fixes` · `/api/fixes/{run_id}` | Fix runs with before/after verification |

The gate is enforced server-side, from stored records, never from client state:

| Situation | Result |
|---|---|
| Apply with no review at all | **409** |
| Apply a **rejected** diagnosis | **409** |
| Apply the same diagnosis twice | **409** |
| Review the same diagnosis twice | **409** — the audit trail is not overwritten |
| `edited` with no reason code or no correction | **422** |
| `rejected` with no reason code or no notes | **422** |
| A request containing a mutation, command, or device | **422** — no request model has such a field |

`POST /api/fixes/apply` takes a `review_id` (or a `diagnosis_id`, whose review the server
looks up itself) and nothing else. The mutations come from the reviewed diagnosis's own
deterministic findings, so a client cannot describe a change it wants made. Every fix run
carries `execution_scope: "simulated_lab_model"` and the verbatim disclaimer *"Verified
against simulated lab model — not executed on physical hardware or Packet Tracer."*

Records are written to `data/diagnoses.json`, `data/reviews.json` and `data/fix_runs.json`
(atomic writes, missing files tolerated). Those three files are gitignored: they are
per-run output, not source.

### Configuration

```bash
cp .env.example .env      # then fill in GEMINI_API_KEY
```

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` (default live) · `mock` (offline, no key) · `anthropic` (declared, not implemented) |
| `LLM_MODEL` | `gemini-3.6-flash` | Gemini Flash model. See the note below. |
| `GEMINI_API_KEY` | — | Free key from <https://aistudio.google.com/apikey> |

**On the model choice.** Verified against the live API on 2026-08-25:
`gemini-3.6-flash`, `gemini-3.5-flash` and `gemini-3.5-flash-lite` all work.
`gemini-3.7-flash` is the newest stable Flash model but currently returns a persistent
`503 "experiencing high demand"` on the free tier, so it is not the default — switch to it
with one line in `.env` when capacity returns. `gemini-2.0-flash` is **shut down**.

Secrets live only in `.env`, which is gitignored. No key is hard-coded, logged, echoed into
an exception message, or returned to a caller. With `LLM_PROVIDER=mock` the whole prototype
runs with no key at all, and every record is stamped `provider: "mock"` so a mock answer can
never be mistaken for a real model answer.

---

## What Phase 2 delivers — the AI diagnosis pipeline

```
DiagnoseRequest ─► Provider ─► AIDiagnosis ─► Evidence Verifier ─► Reconciler ─► Capping
   (5 sections)   (gemini/mock)  (schema)      (deterministic)     (deterministic)
                                                      │                 │            │
                                                      └─────────────────┴────────────┘
                                                    status = awaiting_human_review
                                                            applied = false
```

### Three independent checks on every AI answer

The prompt *asks* for good behaviour; these three components *verify* it. None of them
involves a language model.

**1. Evidence verifier** — every citation's `excerpt` must actually appear in the output of
the `source_command` it names. Whitespace and case are normalised (a reflowed line is still
a real citation); fabrication is not forgiven. A failed citation is recorded and shown to
the reviewer, never silently dropped. Verdicts: `passed` · `partial` · `failed`.

**2. Reconciler** — compares the AI's diagnosis against the deterministic findings:
`agree` · `partial` · `ai_only` · `rules_only` · `conflict`.

**3. Confidence capping** — the model's confidence is an **input**, never the output:

| Condition | Ceiling |
|---|---|
| evidence verification `failed` | **LOW** |
| AI / rule `conflict` | MEDIUM |
| `insufficient_evidence = true` | MEDIUM |
| `ai_only` (nothing corroborates it) | MEDIUM |
| HIGH claimed with < 2 verified citations | MEDIUM |
| otherwise | the model's value is preserved |

`model_confidence` and `effective_confidence` are stored **separately**, so a reviewer can
always see the gap between what the AI claimed and what survived checking. Caps compose —
the lowest ceiling wins.

### Prompt library

| File | Role |
|---|---|
| [`prompts/diagnose_prompt.md`](prompts/diagnose_prompt.md) | primary prompt; 16 hard constraints + **3 worked examples** |
| [`prompts/system_guardrails.md`](prompts/system_guardrails.md) | shared safety preamble, prepended to every call |
| [`prompts/fix_plan_prompt.md`](prompts/fix_plan_prompt.md) | approved root cause → ordered Cisco CLI + verification |
| [`prompts/registry.json`](prompts/registry.json) | name → version → SHA-256, stamped onto every diagnosis |

The three worked examples teach three distinct behaviours: **evidence-gated confidence**
(inter-VLAN/ACL, `medium` until route/ACL evidence exists), **confident diagnosis when
evidence is decisive** (DHCP wrong `default-router`, three corroborating citations), and
**declining to guess** (`insufficient_evidence: true`, empty `fix_steps`, a specific next
command).

Prompt hashes are computed with line endings normalised, so a Windows and a Linux checkout
of the same commit produce the same hash. `load_prompt` **refuses** to load a prompt whose
hash disagrees with the registry — a forgotten `update_prompt_registry` fails loudly instead
of stamping diagnoses with a stale identity.

### Provider abstraction

| Provider | Role |
|---|---|
| `gemini` | default live provider — `google-genai`, stable `models.generate_content`, native structured output |
| `mock` | deterministic, offline, zero-key; derives its diagnosis from the rule findings and quotes real lines from the supplied output |
| `anthropic` | declared stub — reports `is_available() == False` so the factory can never route real traffic into an unimplemented path |

A test asserts that **no module outside `backend/app/ai/gemini_provider.py` imports the
Gemini SDK**, so the abstraction is enforced rather than merely intended. Without a key the
factory falls back to mock *and says so* in a warning attached to the result.

### Two things the live API taught us

Both were caught by writing an actual live test rather than trusting local validation:

1. **The stable endpoint's schema dialect is narrower than the SDK's local validation.**
   `t_schema()` converted our Pydantic model happily, but the API rejected it:
   `Unknown name "additional_properties" ... Cannot find field`. Pydantic's
   `extra="forbid"` emits `additionalProperties`, and nested models emit `$defs`/`$ref` —
   none of which the `generate_content` Schema proto accepts. Rather than weaken the models
   (strict validation is still worth having when parsing the response),
   [`ai/schema_utils.py`](backend/app/ai/schema_utils.py) derives a sanitised wire schema
   from public Pydantic API only. The offline check now asserts against the *proto's*
   constraints, not merely that conversion didn't raise.

2. **`gemini-3.7-flash` is saturated on the free tier.** Four attempts over 4.5 minutes all
   returned 503. The provider now retries transient 429/5xx with exponential backoff, and
   the default model is `gemini-3.6-flash`.

Live result on CASE-001: **4/4 citations verified** across four different commands, correct
root cause, `agree`, HIGH confidence upheld — see
[`reports/live_gemini_smoke_test.txt`](reports/live_gemini_smoke_test.txt).

---

## What Phase 1 delivers

### The six mandatory deterministic rules

The company document names six checks explicitly. All six are implemented and fully
tested — positive tests (the fault is detected) **and** negative tests (no false positive
on a healthy topology) — before any optional rule is written.

| ID | Check | Sub-cases covered |
|---|---|---|
| R001 | Duplicate IP | host↔host · host↔SVI · three-way collisions |
| R002 | Wrong subnet mask | non-contiguous mask · host/gateway mask disagreement · prefix too long for a LAN |
| R003 | Gateway mismatch | gateway outside the host's subnet · gateway owned by no L3 interface · no gateway at all |
| R004 | Interface down | administratively down · line-protocol down · ignores unused spare ports |
| R005 | Missing VLAN | host in an undefined VLAN · access port in an undefined VLAN · SVI for a VLAN never created |
| R006 | Missing route | no connected/static/default route to an intended destination · `ip routing` disabled |

Rules are **pure functions** over a structured `LabState` — no I/O, no AI, no globals —
which is what makes each one testable from a ten-line fixture.

### Why `intended_flows` exists

You cannot decide whether an ACL or a missing route is a *fault* without knowing what the
network is *supposed* to do. Each case therefore declares its intent:

```json
{ "src": "PC-HR", "dst": "SRV-FILES", "proto": "tcp", "port": 445, "expect": "permit" }
```

That turns "does this look wrong?" into a decidable question, and it is what lets R006
(and later R012/R013) be deterministic rather than a matter of opinion.

### The golden test

[`tests/test_golden_expected_faults.py`](tests/test_golden_expected_faults.py) asserts that
the engine fires **exactly** each case's declared `expected_rule_ids` — no missing
detections and no spurious extras. It validates the engine and the dataset in both
directions at once, and it is the mechanism behind the document's grading check *"Python
checker catches basic config errors correctly"*.

Two further guards keep the data honest:

- **`test_show_output_consistency.py`** — every fact in `lab_state` must be visible in the
  Cisco `show` text. The rule engine reasons over the structured state while the AI reasons
  over the text; if those drift apart, the AI would be asked to diagnose a fault it has no
  way to see. This test already caught one real gap during Phase 1.
- **`test_cases_csv_sync.py`** — `data/cases.csv` is generated, never hand-edited, and this
  test fails if the committed deliverable drifts from `data/cases.json`.

### CASE-001 — the representative case

*"HR PC gets an IP but cannot reach the file server in VLAN 30."* A realistic compound
Packet Tracer fault: VLAN 30 was never created on SW1, the `Vlan30` SVI exists but is
administratively shut down, and access port Gi0/2 shows `Access Mode VLAN: 30 (Inactive)`.

It fires **three** of the six mandatory rules (R004, R005, R006) across five findings —
see [`reports/rule_checker_sample_output.txt`](reports/rule_checker_sample_output.txt) for
the checker's actual output.

---

## Project layout

```
backend/
  app/
    config.py            settings from .env (no hard-coded keys)
    netutils.py          pure IPv4 helpers (total functions, never raise)
    store.py             atomic JSON persistence, no database
    models/              enums · lab_state · case · diagnosis (the AI schema)
    rules/
      engine.py          @rule registry, Finding model, runner
      checks/            ip_addressing · gateway · interface · vlan · routing
      cli.py             the deliverable rule checker
    ai/
      base.py            LLMProvider protocol · DiagnoseRequest · ProviderResult
      factory.py         provider selection + no-key fallback
      gemini_provider.py default live provider (the only Gemini import in the codebase)
      mock_provider.py   deterministic offline provider
      schema_utils.py    Pydantic → Gemini wire-schema conversion
      prompt_loader.py   versioned prompt loading + hash enforcement
      evidence_verifier.py   deterministic citation checking
      reconciler.py      AI vs rules, five states
      confidence.py      the capping table
    services/            case_repo · diagnose (the 10-step pipeline)
  scripts/               export_cases_csv · update_prompt_registry
                         phase2_demo · live_diagnose_demo
data/                    cases.json (source of truth) · cases.csv (generated)
prompts/                 diagnose_prompt · system_guardrails · fix_plan_prompt · registry.json
docs/                    PLAN.md — the approved architecture
reports/                 rule_checker_sample_output · test_run
                         phase2_pipeline_demo · live_gemini_smoke_test
tests/                   268 tests (259 offline + 9 live)
```

---

## Honesty commitments

These are enforced in code and in tests, not just documented:

1. **No fix is ever auto-applied.** No code path exists that can push configuration to a
   device. A "fix" mutates a *copy* of the structured `LabState`; verification re-runs the
   deterministic engine and reports the before/after finding diff.
2. **Every verification states its scope**, verbatim: *"Verified against simulated lab
   model — not executed on physical hardware or Packet Tracer."*
3. **No fabricated Packet Tracer execution.** Every case carries
   `source_label: "simulated-lab"` and a test asserts it.
4. **AI evidence is checked, not trusted.** From Phase 2, every AI citation is
   substring-matched against the supplied show output; an unverifiable citation caps
   confidence at LOW and raises a warning rather than being quietly accepted.
5. **Human review is mandatory and server-enforced**, not a UI convention.
