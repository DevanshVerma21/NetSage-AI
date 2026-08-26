# NetSage AI — Architecture

> **AI proposes. Deterministic rules verify. Human approves.**

This document describes what each stage of the pipeline does, what it is allowed to see, and
what it is allowed to change. The central design claim is in §2: the deterministic half of the
system does not depend on the AI half, which is what makes it usable as a check rather than a
second opinion.

---

## 1. The chain

```
Input case
   ↓
LabState
   ↓
Deterministic rule engine
   ↓
AI diagnosis
   ↓
Evidence verifier
   ↓
Reconciler
   ↓
Confidence capping
   ↓
Human review
   ↓
Simulated fix
   ↓
Verification
   ↓
Audit / evaluation
```

### Input case

`data/cases.json` → `backend/app/models/case.py` → `case_repo.all_cases()`.

A case is a captured fault: `symptom`, `topology_note`, a `lab_state`, the device
`show_outputs` verbatim, the `intended_flows` the network is supposed to permit or deny, and
the authored ground truth (`expected_fault`, `expected_rule_ids`,
`expected_root_cause_keywords`, `expected_fix_steps`).

All 40 cases carry `source_label: "simulated-lab"`. Ground truth is written when the case is
authored and is never edited after seeing a model answer.

### LabState

`backend/app/models/lab_state.py`.

The structured view: devices, interfaces with addresses and admin/line state, VLAN databases,
access and trunk configuration, SVIs, routing tables, ACLs, DHCP pools, DNS settings, NAT
configuration, wireless SSIDs, and hosts with their gateways and resolvers.

A companion test (`test_show_output_consistency.py`) requires every fact in `lab_state` to be
visible in the `show` text. The rule engine reasons over the structure; the AI reasons over the
text. If the two drifted apart, the AI would be asked to diagnose a fault it has no way to see.

### Deterministic rule engine

`backend/app/rules/engine.py` and `backend/app/rules/checks/`.

15 registered rules — R001–R006 mandatory, R007–R015 optional. Each is a **pure function**
`(LabState, intended_flows) → list[Finding]`: no I/O, no globals, no AI, and no mutation of the
state it is given. `run_rules(state, flows, only=None)` collects the findings.

A `Finding` names its rule, severity, OSI layer, the device and interface involved, a
human-readable explanation, and the `show` commands that confirm it.

This stage runs **before** the AI and does not receive the AI's output, now or later.

### AI diagnosis

`backend/app/services/diagnose.py` → `backend/app/ai/`.

`DiagnoseRequest.from_case(case, rule_findings)` assembles the prompt input: the symptom, the
topology note, the intended flows, the **full untruncated** show output, and the deterministic
findings. `load_prompt("diagnose_prompt")` refuses to proceed if the prompt file's SHA-256 does
not match `prompts/registry.json`, so every record can be traced to an exact prompt text.

The provider — `gemini` live, `mock` offline, `anthropic` a declared stub that reports itself
unavailable — returns a structured `AIDiagnosis`: root cause, OSI layer, category, citations
(each naming a `source_command` and quoting an `excerpt`), fix steps, a self-reported
confidence, and an explicit `insufficient_evidence` flag.

Only `gemini_provider.py` imports the Gemini SDK; a test asserts that no other module does.

### Evidence verifier

`backend/app/ai/evidence_verifier.py` — pure Python, no model.

Each citation's excerpt must actually appear in the output of the command it names.
Whitespace and case are normalised, so a reflowed line still counts; anything that is not
present is recorded as `excerpt_not_found`, `unknown_source_command`, or `empty_excerpt`.
The verdict is `passed`, `partial`, or `failed`, and failed citations are surfaced to the
reviewer rather than dropped.

The verifier is treated as fixed. When a prompt version produced unverifiable citations, the
prompt was corrected and the verifier was left alone — otherwise the check would drift toward
whatever the model happens to emit.

### Reconciler

`backend/app/ai/reconciler.py` — pure Python, no model.

Compares the AI's conclusion against the rule findings and returns one of five states:

| State | Meaning |
|---|---|
| `agree` | The AI identified what the rules found |
| `partial` | Overlapping but incomplete on one side |
| `ai_only` | The AI claims something no rule corroborates |
| `rules_only` | The rules found something the AI missed |
| `conflict` | The two disagree substantively |

### Confidence capping

`backend/app/ai/confidence.py` — a table, not a model.

The model's confidence is an input. Ceilings compose and the lowest wins:

| Condition | Ceiling |
|---|---|
| evidence verification `failed` | **LOW** |
| AI / rule `conflict` | MEDIUM |
| `insufficient_evidence = true` | MEDIUM |
| `ai_only` | MEDIUM |
| HIGH claimed with fewer than 2 verified citations | MEDIUM |
| otherwise | preserved |

`model_confidence` and `effective_confidence` are stored separately, so the gap between what
the model claimed and what survived checking is always visible.

The pipeline's output is a `DiagnosisResult` carrying the AI answer, the rule findings, the
verification, the reconciliation, both confidences, latency, provider, model, prompt version and
hash, and token usage. It is persisted with `status = "awaiting_human_review"` and
`applied = false`, always.

### Human review

`backend/app/services/review_service.py`, `POST /api/reviews`.

A verdict is `accepted`, `edited`, or `rejected`, with a reason code and — for `edited` and
`rejected` — a correction or notes, enforced by validation (`422` otherwise). Reviews are
write-once: reviewing the same diagnosis twice returns `409`, so the audit trail cannot be
overwritten.

The gate is evaluated **server-side from stored records**. The frontend does not decide it; the
Triage Workbench simply has no fix control until a verdict exists.

### Simulated fix

`backend/app/services/fix_simulator.py`, `POST /api/fixes/apply`.

The request carries a `review_id` (or a `diagnosis_id` whose review the server looks up) **and
nothing else**. A client cannot describe a change it wants made. The mutations are derived from
the reviewed diagnosis's own deterministic findings.

The simulator deep-copies the `LabState` and applies those mutations to the copy. There is no
SSH, Telnet, Netmiko, paramiko, scrapli, `subprocess`, or shell execution anywhere in the
codebase. Nothing reaches a device, real or emulated.

Applying a rejected diagnosis, an unreviewed diagnosis, or the same diagnosis twice returns
`409`.

### Verification

The rule engine is re-run over the mutated copy, and the two finding sets are diffed: resolved,
still present, newly appeared. The check that judges the fix is therefore the same
deterministic engine that found the fault — not the model that proposed it.

Every fix run carries `execution_scope: "simulated_lab_model"` and the disclaimer verbatim:

> Verified against simulated lab model — not executed on physical hardware or Packet Tracer.

### Audit / evaluation

`data/diagnoses.json`, `data/reviews.json`, `data/fix_runs.json` (atomic writes, gitignored as
per-run output), and `data/evaluation_results.json` plus its archived predecessor.

`backend/app/services/evaluation.py` grades a stored record against the case's authored ground
truth — rule agreement, keyword agreement, OSI and category agreement — and
`backend/app/services/dashboard.py` aggregates. Failed provider calls and invalidated records
are **retained** and counted as not evaluated; they are never promoted into results.

---

## 2. Why the deterministic checks are independent of the AI

A verifier that shares a failure mode with the thing it verifies is not a verifier. Four
concrete properties keep the two halves apart:

**The rule engine never reads the model's output.** `run_rules` takes a `LabState` and the
intended flows. It has no parameter through which an AI answer could reach it, and it runs
before the provider is called. Whatever the model says cannot change what the rules found.

**The rules are pure functions.** No I/O, no globals, no mutation of their input. Two runs over
the same state produce the same findings, which is why a finding can be treated as a fact about
the case rather than an observation about a particular run.

**No model is involved in verification, reconciliation, or capping.** The evidence verifier is
string normalisation and substring matching. The reconciler is set comparison. The capping table
is a table. None of the three can be talked out of a conclusion.

**The fix is judged by the engine, not the proposer.** Verification re-runs the same
deterministic rules over the mutated copy. A model cannot certify its own fix.

The practical consequence is the one that matters for reporting: **the deterministic results are
valid whether or not the AI evaluation ever completes.** 40 cases, 15 rules, golden
expected-vs-fired PASS, rule pass rate 1.0 — none of that depends on a Gemini call. That is why
the dashboard keeps two separate blocks with two separate denominators and no combined score:
one half is measured, the other is not, and merging them would hide that.

---

## 3. What the system cannot do

Not a policy statement — an absence of code, verified by sweep and by test:

- It cannot connect to a device. No SSH, Telnet, Netmiko, paramiko, or scrapli.
- It cannot execute a command. No `subprocess`, `os.system`, `eval`, `exec`, or `shell=True`
  in `backend/app/`.
- It cannot apply a fix to anything but an in-memory copy of a structured model.
- It cannot accept a mutation, command, or device address from a client. No request model has
  such a field.
- It cannot apply a rejected or unreviewed diagnosis.
- It cannot bypass the human review gate.
- It cannot return, log, or print an API key.

---

## 4. Storage

JSON files under `DATA_DIR`, written atomically, with missing files tolerated as empty. No
database, deliberately: the dataset is 40 cases, and keeping it in a diffable file makes ground
truth reviewable — which matters more here than query performance. `store.py` is the only
module that touches the filesystem for records.

Source data (`cases.json`, `cases.csv`, `evaluation_results.json`, the v1.0.0 archive) is
committed. Per-run output (`diagnoses.json`, `reviews.json`, `fix_runs.json`) is gitignored.

---

## 5. The frontend

React 19 with react-router-dom 7, Vite 8, Tailwind 4. No component library.

Six routes: `/` (Dashboard), `/cases`, `/cases/:caseId` (Triage Workbench),
`/review/:diagnosisId`, `/fixes/:reviewId`, `/responsible-ai`.

Two conventions carry the architecture into the interface. First, the Triage Workbench puts
the deterministic findings **above** the AI proposal, and runs the rule check automatically on
load — an operator sees what the engine proved before being shown what a model thinks. Second,
the display components accept only values the backend already calculated: `Stat` and `Bar` do
no arithmetic, and `accuracy` renders as the literal word *withheld* when the API returns
`null`. The honesty property is therefore a structural feature of the components rather than a
matter of wording.

The browser holds no absolute backend URL — the dev server proxies `/api` — so there is nowhere
in the bundle a credential could live.
