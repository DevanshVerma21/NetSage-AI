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
| 2 | AI layer: prompts · provider abstraction · Gemini · mock · evidence verifier · reconciler | ⏳ next |
| 3 | API · server-enforced review gate · Fix Simulator · verification | — |
| 4 | Frontend vertical slice, CASE-001 proven end to end | — |
| 5 | Expand to 40 cases · optional rules R007–R015 | — |
| 6 | Dashboard · Responsible AI log from a live batch run | — |
| 7 | Deliverables · docs · demo script | — |

**Phase 1 test result: 99 passed, 2 skipped** (the 2 skips are deliberate Phase 5 dataset
gates that arm themselves once the dataset reaches 40 cases). Full log:
[`reports/test_run.txt`](reports/test_run.txt).

---

## Quick start

Requires Python 3.11+. Everything in Phase 1 runs offline with no API key.

```bash
# 1. Install backend dependencies
pip install -r backend/requirements.txt

# 2. Run the test suite
python -m pytest tests -q

# 3. Run the deterministic rule checker (no AI, no network)
python -m backend.app.rules.cli --list-rules
python -m backend.app.rules.cli --case CASE-001
python -m backend.app.rules.cli --all --check-expected

# 4. Regenerate the cases.csv deliverable after any dataset edit
python -m backend.scripts.export_cases_csv
```

### Configuration

```bash
cp .env.example .env      # then fill in GEMINI_API_KEY
```

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` (default live) · `mock` (offline, no key) · `anthropic` (optional) |
| `LLM_MODEL` | `gemini-3.7-flash` | Current stable Gemini Flash model. `gemini-2.0-flash` is shut down. |
| `GEMINI_API_KEY` | — | Free key from <https://aistudio.google.com/apikey> |

Secrets live only in `.env`, which is gitignored. No key is ever hard-coded or logged.
With `LLM_PROVIDER=mock` the whole prototype runs with no key at all, and every stored
record is stamped `provider: "mock"` so a mock answer can never be mistaken for a real
model answer.

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
    models/              enums · lab_state · case
    rules/
      engine.py          @rule registry, Finding model, runner
      checks/            ip_addressing · gateway · interface · vlan · routing
      cli.py             the deliverable rule checker
    services/            case_repo
  scripts/               export_cases_csv
data/                    cases.json (source of truth) · cases.csv (generated)
docs/                    PLAN.md — the approved architecture
reports/                 rule_checker_sample_output.txt · test_run.txt
tests/                   101 tests
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
