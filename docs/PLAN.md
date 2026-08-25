# NetSage AI — Architecture Plan (v2, approved with amendments)

**Status:** approved 2026-08-25. Amendments 1–13 from the reviewer are folded in below.
**Engineering principle:** *AI proposes. Deterministic rules verify. Human approves.*
**Company document:** `AI_Problem Statement.docx` (note: the actual filename contains a
space, not an underscore).

---

## 0. What changed from v1

| # | Amendment | Where it lands |
|---|---|---|
| 1 | **Gemini is the default live provider** (free tier). Priority: `gemini` → `mock` → `anthropic` (optional future). | §5 |
| 2 | Dataset **40 cases**, fixed distribution incl. a 9th category `INTERFACE_CONFIG` | §3, §8 |
| 3 | **R001–R006 fully tested before any optional rule** | §4, §8 |
| 4 | Evidence verifier retained, with explicit failure contract | §6 |
| 5 | Fix Simulator retained, with mandatory scope disclaimer string | §7 |
| 6 | Mandatory human review, server-enforced | §7 |
| 7 | Evidence-gated confidence with explicit capping table | §6 |
| 8 | **One complete vertical slice before the 40-case dataset** | §8 |
| 9 | Lean frontend — 6 pages, no animation work | §9 |
| 10 | All dashboard metrics computed from stored data | §9 |
| 11 | Responsible-AI log harvested from a **real** batch run, never fabricated | §10 |
| 12 | Company deliverables preserved at exact paths | §11 |
| 13 | Phased delivery, tests run at every phase boundary | §8 |

---

## 1. Requirement traceability

Full requirement-by-requirement mapping lives in `docs/REQUIREMENTS_TRACE.md`
(generated in Phase 7). Summary of the six graded pass conditions:

| Grading check (from the document) | Mechanism | Proof artifact |
|---|---|---|
| ≥30 cases across multiple fault types | 40 cases, 9 categories | `tests/test_dataset.py` |
| AI responses quote **actual** show-command evidence | `evidence_verifier.py` — deterministic substring match | `tests/test_evidence_verifier.py` |
| Reviewer log shows accepted, edited **and** rejected | Review model + server-side gate | `tests/test_api_gates.py` |
| Python checker catches basic config errors correctly | Golden test: engine output == case's `expected_rule_ids` | `tests/test_golden_expected_faults.py` |
| ≥5 documented AI corrections | Harvested from a live batch run | `tests/test_responsible_ai_log.py` |
| Demo: broken → diagnosed → reviewed → fixed → verified | Fix Simulator over `LabState` | `demo/DEMO_SCRIPT.md` |

---

## 2. Pipeline

```
Case or pasted input
   │
   ▼
[1] Normalize ────────── LabState (structured facts) + show_outputs (Cisco text)
   │
   ▼
[2] RULE ENGINE (pre) ── deterministic Findings. Runs FIRST, no AI involved.
   │                     Findings are fed INTO the prompt as verified context.
   ▼
[3] AI DIAGNOSER ─────── schema-enforced JSON (Gemini response_schema)
   │
   ▼
[4] EVIDENCE VERIFIER ── every citation must exist in the supplied output
   │                     fail ⇒ evidence_integrity="failed" ⇒ confidence capped LOW
   ▼
[5] RECONCILER ───────── agree | partial | ai_only | rules_only | conflict
   │                     conflict ⇒ confidence capped MEDIUM
   ▼
[6] PERSIST ──────────── status="awaiting_human_review", applied=false. ALWAYS.
   │
   ▼
[7] HUMAN REVIEW GATE ── Accepted | Edited | Rejected (+ reason_code, notes)
   │                     No review ⇒ no fix. HTTP 409. Rejected ⇒ HTTP 409.
   ▼
[8] FIX SIMULATOR ────── approved mutations applied to a COPY of the LabState
   │
   ▼
[9] RULE ENGINE (post) ─ re-run. before/after finding diff = the verification.
                         Always labelled with the simulated-scope disclaimer.
```

---

## 3. Data model

### 3.1 Case (`data/cases.json` is the single source of truth)

`case_id` · `title` · `symptom` · `topology_note` · `show_outputs[{device,command,output}]`
· `expected_fault` · `expected_root_cause_keywords[]` · `osi_layer` · `concept_tag`
· `severity` · `security_relevant` · `lab_state` · `intended_flows[]`
· `expected_rule_ids[]` · `expected_fix_steps[]` · `source_label="simulated-lab"`

`data/cases.csv` is **generated** by `backend/scripts/export_cases_csv.py`.
A test fails if the committed CSV drifts from the JSON, so the graded deliverable
can never go stale.

### 3.2 Dataset distribution (40 cases, amendment 2)

| concept_tag | count |
|---|---|
| VLAN | 5 |
| GATEWAY | 5 |
| DHCP | 5 |
| DNS | 4 |
| ROUTING | 5 |
| ACL | 4 |
| NAT | 4 |
| WIRELESS | 4 |
| INTERFACE_CONFIG | 4 |
| **Total** | **40** |

### 3.3 LabState

```
LabState
├── devices[]  name, kind, ip_routing_enabled, interfaces[], vlans[], routes[],
│              acls[], acl_bindings[], dhcp_pools[], nat_rules[], ssids[]
├── hosts[]    name, ip, mask, gateway, dns_servers[], vlan, connected_device/interface
└── links[]    a_device/a_iface, b_device/b_iface, mode, access_vlan,
               allowed_vlans[], native_vlan
```

`intended_flows[]` (`src`, `dst`, `proto`, `port`, `expect: permit|deny`) declares what
the network is *supposed* to do. Without it, "is this ACL wrong?" is undecidable;
with it, R006/R012/R013 become deterministic pass/fail checks.

### 3.4 Records (append-only JSON)

- **Diagnosis** — `provider`, `model`, `prompt_version`, `prompt_sha256`, `rule_findings[]`,
  `ai{...}`, `evidence_integrity`, `reconciliation`, `effective_confidence`,
  `status="awaiting_human_review"`, `applied=false`, `latency_ms`, `token_usage`
- **Review** — `verdict`, `corrected_*`, `reason_code` (**required** when verdict ≠ Accepted),
  `notes`, `agreement{root_cause,osi_layer,category}`, `reviewer`, `reviewed_at`
- **FixRun** — `mutations[]`, `findings_before[]`, `findings_after[]`, `resolved_rule_ids[]`,
  `new_rule_ids[]`, `verification_result`, `execution_scope="simulated_lab_model"`
- **ResponsibleAILogEntry** — `ai_said`, `human_said`, `failure_mode`, `why_ai_was_wrong`,
  `human_correction`, `lesson`, links to the real diagnosis + review

**Storage:** `store.py` — atomic JSON writes (`tmp` + `os.replace`) under a lock. No database.

---

## 4. Rule checker (amendment 3)

Rules are **pure functions over `LabState`**, registered by decorator, so each is unit
testable from a small fixture.

### 4.1 Mandatory — built and fully tested FIRST (Phase 1)

| ID | Check | Sub-cases |
|---|---|---|
| R001 | **Duplicate IP** | same address owned by 2+ interfaces/hosts |
| R002 | **Wrong subnet mask** | non-contiguous mask · host mask ≠ gateway's interface mask · host/31–/32 on a LAN |
| R003 | **Gateway mismatch** | gateway outside the host's own subnet · gateway owned by no L3 interface |
| R004 | **Interface down** | `administratively down` · `down/down` on an IP-bearing, linked, or SVI interface |
| R005 | **Missing VLAN** | VLAN referenced by a host or access port but absent from the switch VLAN database |
| R006 | **Missing route** | no connected/static/default route covering an intended-flow destination |

**Gate: no optional rule is written until R001–R006 are green with positive *and*
negative (no-false-positive) tests.**

### 4.2 Optional — Phase 5

R007 access-VLAN mismatch · R008 trunk/native-VLAN mismatch · R009 overlapping subnets ·
R010 DHCP (pool/subnet, `default-router`, `ip helper-address`) · R011 DNS ·
R012 ACL blocks an intended flow (5-tuple evaluator + implicit deny) ·
R013 NAT (inside/outside, pool, matching ACL) · R014 wireless guest isolation ·
R015 SVI shutdown / missing SVI

### 4.3 Deliverable CLI

```
python -m backend.app.rules.cli --case CASE-001
python -m backend.app.rules.cli --all --format table > reports/rule_checker_sample_output.txt
```

---

## 5. AI layer (amendment 1)

### 5.1 Provider abstraction

```python
class LLMProvider(Protocol):
    name: str
    model: str
    def diagnose(self, req: DiagnoseRequest) -> ProviderResult: ...
```

| Provider | Role | Notes |
|---|---|---|
| `gemini` | **default live provider** | `google-genai` (already installed, v1.63.0) |
| `mock` | deterministic offline fallback | zero-key; every record stamped `provider="mock"` so it is never mistaken for a real model answer |
| `anthropic` | optional future provider | stub + documented; not wired by default |

### 5.2 Gemini call shape (verified against the installed SDK)

Uses the **stable** `client.models.generate_content` path with native structured output:

```python
from google import genai
from google.genai import types

client = genai.Client()               # reads GEMINI_API_KEY from the environment
resp = client.models.generate_content(
    model=settings.llm_model,          # gemini-3.7-flash
    contents=user_prompt,
    config=types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=AIDiagnosis,   # Pydantic model — schema enforced server-side
        temperature=0.1,
    ),
)
diagnosis = resp.parsed                # typed AIDiagnosis
```

`client.interactions` (the newer Interactions API) is **deliberately not used**: the
installed SDK emits `UserWarning: Interactions usage is experimental and may change in
future versions`. Recorded as the future migration target in `docs/ARCHITECTURE.md`.

### 5.3 Environment variables — no hard-coded keys

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.7-flash
GEMINI_API_KEY=            # .env only; .env is gitignored; .env.example committed
ANTHROPIC_API_KEY=         # optional, unused by default
```

`gemini-3.7-flash` is the current stable Flash model (verified 2026-08-25).
`gemini-2.0-flash` is shut down — do not use. Model ID is env-configurable so it can be
changed without touching code.

### 5.4 Prompt library

| File | Role |
|---|---|
| `prompts/diagnose_prompt.md` | **primary** (exact filename required by the document) |
| `prompts/system_guardrails.md` | shared safety preamble |
| `prompts/fix_plan_prompt.md` | approved root cause → ordered Cisco CLI + verification |
| `prompts/registry.json` | name → version + sha256, stamped onto every diagnosis |

Three worked examples in `diagnose_prompt.md` (the document asks for 2–3):
1. **inter-VLAN / ACL** — the document's own example; teaches evidence-gated `medium` confidence
2. **DHCP wrong `default-router`** — teaches confident diagnosis when evidence is decisive
3. **insufficient evidence** — teaches `insufficient_evidence: true` + a specific `next_command`

### 5.5 Output schema

Field names are the document's, verbatim: `root_cause`, `confidence`, `evidence`,
`next_command`, `fix_steps` — plus `confidence_score`, `osi_layer`, `category`,
`insufficient_evidence`, `alternative_hypotheses`, `verification_steps`,
`notes_for_reviewer`.

---

## 6. Evidence verification & confidence capping (amendments 4, 7)

### 6.1 Evidence verifier contract

Every `evidence[].excerpt` must appear (whitespace-normalised) in the show output of its
declared `source_command`. Result: `passed` | `partial` | `failed`.

**On `failed`:** `effective_confidence` capped at **LOW**, a red warning is rendered, and
human review remains mandatory. The diagnosis is never discarded — the reviewer sees both
the claim and the fact that it could not be substantiated.

### 6.2 Confidence capping table (backend post-processing, not prompt-dependent)

| Condition | Ceiling |
|---|---|
| evidence verification `failed` | LOW |
| AI / rule-engine `conflict` | MEDIUM |
| `insufficient_evidence = true` | MEDIUM |
| `ai_only` (no corroborating rule finding) | MEDIUM |
| HIGH requested with < 2 verified evidence items | MEDIUM |

The model's self-reported confidence is an *input* to this function, never the output.

---

## 7. Fix Simulator & human gate (amendments 5, 6)

### 7.1 Honesty contract

Every verification result carries, verbatim:

> **Verified against simulated lab model — not executed on physical hardware or Packet Tracer.**

A "fix" is a list of typed mutations (`add_vlan`, `set_interface_admin_state`,
`set_host_gateway`, `add_static_route`, `insert_acl_entry`, …) applied to a **copy** of the
`LabState`. The engine is then re-run and the before/after finding diff *is* the
verification. This is a real, deterministic, reproducible state transition — so the claim
is true, and its scope is stated everywhere it appears.

**No code path exists that can push configuration to a device.** Recorded as an ADR.

### 7.2 Server-enforced review gate

`POST /api/fixes/apply` returns **409** unless all hold:
- a review exists for the diagnosis
- verdict is `Accepted` or `Edited`
- required review fields are present (`reason_code` when verdict ≠ Accepted)
- the fix has not already been applied

`Rejected` diagnoses can never be applied. Enforced in the endpoint, not the UI.

---

## 8. Phased delivery (amendments 8, 13)

Tests run at every phase boundary. **Work stops at each boundary for review.**

| Phase | Scope | Test gate |
|---|---|---|
| **1** | Foundation + **R001–R006 fully tested** + 1 representative case (CASE-001) + rules CLI | rule unit tests (pos + neg) · case schema · golden expected-faults |
| **2** | AI layer: prompts · provider abstraction · Gemini · mock · evidence verifier · reconciler · confidence capping | verifier · reconciler · capping table · mock determinism |
| **3** | API + gates + Fix Simulator + verification | 409/422 gate tests · fix-simulator before/after |
| **4** | Frontend vertical slice — Case Library · Triage Workbench · Review · Fix & Verify. **End-to-end run of CASE-001.** | manual E2E + API smoke |
| **5** | Expand to **40 cases** + optional rules R007–R015 | full golden matrix · category coverage |
| **6** | Dashboard + Responsible AI page + **live Gemini batch run** + genuine correction harvest | dashboard computed-not-hardcoded · ≥5 real log entries |
| **7** | Deliverables · docs · demo script · final full test run | complete suite green |

Phase 1–4 constitute the single vertical slice required by amendment 8: one case proven
end-to-end through every layer before the dataset is scaled to 40.

---

## 9. Frontend (amendments 9, 10)

Six pages, no animation work, no chart library (hand-rolled inline SVG).
Dependencies: `react`, `react-dom`, `react-router-dom`, `vite`, `tailwindcss`.

| Page | Purpose |
|---|---|
| Case Library | filterable table + category-coverage strip |
| **Triage Workbench** | show outputs (left) · rule findings → AI diagnosis → reconciliation (right) · sticky review bar (bottom) |
| Human Review | Accept / Edit / Reject with required reason code |
| Fix & Verify | approved delta · apply to simulated model · before/after diff · scope disclaimer |
| Dashboard | issue types · severity · AI-vs-human agreement · rule-hit frequency — **all computed from `/api/dashboard`** |
| Responsible AI | corrections table + failure-mode histogram |

An unreviewed diagnosis renders with a dashed amber border and the label
*"Proposed — awaiting human review"*. Fix & Verify is unreachable without a verdict.

---

## 10. Responsible AI log (amendment 11)

Phase 6 runs a **real** Gemini batch diagnosis across all 40 cases, compares each result
with `expected_fault`, and surfaces genuine disagreements for human review. At least 5
entries where a human **corrected, rejected, or materially edited** the AI result are then
recorded with failure mode, reason and lesson.

**These are not authored.** If the live run yields fewer than 5 genuine corrections, the
shortfall is reported rather than topped up with invented entries.

---

## 11. Preserved company deliverables (amendment 12)

| Deliverable | Exact path |
|---|---|
| Case dataset | `data/cases.csv` (generated from `data/cases.json`) |
| Primary prompt | `prompts/diagnose_prompt.md` |
| Python checker + sample output | `backend/app/rules/cli.py` + `reports/rule_checker_sample_output.txt` |
| Dashboard | in-app page + `reports/dashboard_snapshot.md` |
| Responsible AI log | `data/responsible_ai_log.json` + `docs/RESPONSIBLE_AI.md` |
| Demo script | `demo/DEMO_SCRIPT.md` (5–10 min shot list) |

---

## 12. Testing strategy

| Suite | Covers |
|---|---|
| `tests/rules/test_r001..r015.py` | ≥2 tests per rule: detects the fault · no false positive on a clean state |
| `test_dataset.py` | 40 cases · all 9 categories · unique IDs · required fields non-empty · `source_label` set |
| `test_cases_csv_sync.py` | regenerated CSV matches the committed deliverable byte-for-byte |
| `test_golden_expected_faults.py` | engine output == each case's `expected_rule_ids`; emits `reports/coverage_matrix.md` |
| `test_show_output_consistency.py` | facts in `lab_state` actually appear in that case's show text |
| `test_evidence_verifier.py` | fabricated citation → `failed`; real citation → `passed` |
| `test_confidence_capping.py` | the full §6.2 table |
| `test_reconciler.py` | all five agreement classes |
| `test_api_gates.py` | 409 without review · 409 on Rejected · 409 on double-apply · diagnose always `awaiting_human_review` |
| `test_fix_simulator.py` | mutation resolves the target rule · no new findings · `execution_scope` correct |
| `test_dashboard.py` | every metric computed from a synthetic store; no literals in the response |
| `test_responsible_ai_log.py` | ≥5 entries, each linked to a real review with verdict ≠ Accepted |

Zero network calls in the default suite (mock provider only). The live Gemini path is an
opt-in `@pytest.mark.live` test.
