# NetSage AI — Evaluation

What has been measured, how, and what has **not** been measured.

The distinction that governs this whole document: the **deterministic** results are validated
and complete; the **live Gemini** results are not. They are reported separately, with separate
denominators, and are never combined into a single score. Where a number is missing it is
stated as missing rather than estimated.

| Half | Status | Figure |
|---|---|---|
| Deterministic rule engine | **validated, complete** | 40/40 cases, golden expected-vs-fired **PASS**, rule pass rate **1.0** |
| Live Gemini evaluation | **incomplete — quota blocked** | **0 of 40** official evaluations; no accuracy figure exists |
| Human review | **incomplete** | 0 recorded reviews; 5 genuine corrections required |

---

## 1. The 40-case dataset

`data/cases.json` is the source of truth; `data/cases.csv` is generated from it and a test
fails if the two drift apart.

| Dimension | Composition |
|---|---|
| Concept tag | GATEWAY 5 · VLAN 5 · ROUTING 5 · DHCP 5 · ACL 4 · DNS 4 · NAT 4 · WIRELESS 4 · INTERFACE_CONFIG 4 |
| Severity | Critical 8 · High 30 · Medium 2 |
| OSI layer | L1 2 · L2 8 · L3 22 · L4 4 · L7 4 |
| Security-relevant | 5 |
| Compound faults (>1 expected rule) | 8 |
| `source_label` | `simulated-lab` — all 40 |

Each case declares its own ground truth: `expected_fault`, `expected_rule_ids`,
`expected_root_cause_keywords`, `expected_fix_steps`, plus `osi_layer` and `concept_tag`.

**Ground truth is read-only.** It was fixed when the case was authored and has not been edited
after any AI output was seen. No evaluation script writes to `data/cases.json`. This is the
property the whole evaluation rests on; if it were violated, every number below would be
meaningless.

The dataset is **self-authored and simulated**. It is not a sample of real production faults,
and no result here should be read as a measurement against real-world incident data.

## 2. The 15 deterministic rules

R001–R006 are the mandatory checks named in the problem statement; R007–R015 extend coverage to
the rest of the dataset's fault space. Full catalogue with detection criteria and confirming
commands: `python -m backend.app.rules.cli --list-rules`, or the table in
[`../README.md`](../README.md).

Expected-rule coverage across the dataset:

| Rule | Cases | Rule | Cases | Rule | Cases |
|---|--:|---|--:|---|--:|
| R001 | 1 | R006 | 6 | R011 | 4 |
| R002 | 2 | R007 | 1 | R012 | 4 |
| R003 | 6 | R008 | 2 | R013 | 4 |
| R004 | 5 | R009 | 1 | R014 | 4 |
| R005 | 2 | R010 | 5 | R015 | 3 |

Every rule is exercised by at least one case. Each also has direct unit tests: positive (the
fault is detected) **and** negative (no false positive on a healthy topology).

## 3. Golden testing — the deterministic result

`tests/test_golden_expected_faults.py` runs the engine over every case and asserts it fires
**exactly** the case's `expected_rule_ids`: no missed detection, and no spurious extra. It
validates the engine and the dataset in both directions simultaneously.

Current result, recomputed live by `dashboard_service.deterministic_summary()` on every request
rather than read from a log:

| Measure | Value |
|---|---|
| Cases | 40 |
| Rules registered | 15 (6 mandatory + 9 optional) |
| Cases matching expected rules | 40 |
| Cases not matching | 0 |
| Mismatches | none |
| Golden case result | **PASS** |
| Rule pass rate | **1.0** |

This is the one accuracy-shaped number in the system that is complete, and it is a
deterministic result about the engine — **not an AI performance figure**. It involves no model
call and would be unchanged if no provider were ever configured.

Two supporting guards:

- `test_show_output_consistency.py` — every fact in `lab_state` must be visible in the `show`
  text, so the AI is never asked to diagnose something it cannot see.
- `test_cases_csv_sync.py` — the generated CSV deliverable must match `cases.json`.

Test suite: **532 offline tests pass**; 9 live-provider tests are deselected by default
(`-m 'not live'` in `pyproject.toml`), so an ordinary run never calls Gemini.

## 4. Evidence verification

`backend/app/ai/evidence_verifier.py`. Deterministic, no model.

Every citation names a `source_command` and quotes an `excerpt`; the excerpt must appear in that
command's actual output for that case. Both sides are normalised
(`re.sub(r"\s+", " ", text).strip().lower()`) so a reflowed or re-cased line still counts, but a
line that is not there is not forgiven. Failures are recorded with a reason —
`excerpt_not_found`, `unknown_source_command`, `empty_excerpt` — and kept with their original
text. Per-diagnosis verdict: `passed` · `partial` · `failed`.

Corpus-wide the evaluation records total citations, verified citations, failed citations and a
verification rate. **Those figures are currently all zero, because no official evaluation record
exists.**

An important scope limit: verification proves a citation is *real*, not that the conclusion drawn
from it is *right*. A model can quote genuine output and still misread it. That is one reason the
human gate is mandatory rather than advisory.

## 5. AI evaluation methodology

The grading scheme was fixed **before** the first batch ran and is documented in full, including
both thresholds and the classification order, in
[`evaluation_methodology.md`](evaluation_methodology.md). Implementation:
`backend/app/services/evaluation.py`. Summary:

- **The model never grades itself.** Gemini is asked for a diagnosis and nothing else. Every
  comparison is a set or substring operation performed in Python against `data/cases.json`.
- **Four comparisons per case:** rule agreement (an expected rule appears in the reconciler's
  matched rules), root-cause keyword agreement (`keyword_hit_rate >= 0.5`), OSI-layer exact
  match, category exact match.
- **Fixed thresholds:** `KEYWORD_RATE_FOR_CORRECT = 0.5`, `KEYWORD_RATE_FOR_PARTIAL = 0.25`.
  Stated in advance so a reader can confirm they were not moved to flatter a score.
- **Verdicts:** `UNABLE_TO_EVALUATE` · `CORRECT` · `PARTIAL` · `INCORRECT`, evaluated in that
  documented order, with the unmet conditions recorded in `classification_reason`.
  `CORRECT` requires evidence integrity not to be `failed`: a diagnosis that is right but
  unsubstantiated is not counted as correct.
- **Nothing is dropped.** A failed API call is stored with `evaluation_status = "failed"` and
  counted in every total.

What the verdict is **not**: it is not a judgement of whether the fix steps would work (that is
the simulator's job), it is not a human judgement, and `CORRECT` does not mean safe to apply —
every diagnosis stays `awaiting_human_review` with `applied = false` regardless.

## 6. Confidence handling

The model's confidence is an input to the record, never its output. Ceilings compose; the lowest
wins:

| Condition | Ceiling |
|---|---|
| evidence verification `failed` | **LOW** |
| AI / rule `conflict` | MEDIUM |
| `insufficient_evidence = true` | MEDIUM |
| `ai_only` | MEDIUM |
| HIGH claimed with fewer than 2 verified citations | MEDIUM |
| otherwise | preserved |

`model_confidence` and `effective_confidence` are stored separately and reported separately, so
the gap between claim and survival is visible per case.

The metrics deliberately include the cross-tabulations that matter for responsible AI —
high-confidence-but-incorrect, high-confidence-partial, low-confidence-correct,
medium-confidence-correct — because a calibration failure is a different problem from an accuracy
failure and should not be averaged into one. **All of these are currently empty for want of
official records.**

## 7. Human-review methodology

Human review is mandatory, write-once, and enforced by the backend from stored records.

- A verdict is `accepted`, `edited`, or `rejected`, with a reason code; `edited` requires a
  correction and `rejected` requires notes, or the request is rejected with `422`.
- Reviewing the same diagnosis twice returns `409`: the audit trail is not overwritten.
- A **correction** is an `edited` or `rejected` verdict. The Responsible AI requirement is
  **5 genuine corrections**, and the target is reported as a target, never as an achievement.
- Human disagreement with a mechanical verdict is recorded separately and never overwrites it.

Reviews are collected by a person working through
`python -m backend.scripts.review_candidates` in a terminal. **No review has been fabricated to
satisfy the requirement.**

Current state: **0 recorded reviews**, 0 corrections against a requirement of 5. The dashboard
reports *"Human review data incomplete"* and `data/responsible_ai_log.json` does not exist, so the
correction log renders an empty state rather than illustrative examples.

## 8. Current evaluation coverage

**Official Gemini evaluations: 0 of 40.** There is no AI accuracy figure, and the absence is not
a placeholder for a good one — it is simply unmeasured.

`dashboard_service.ai_evaluation_summary()` reports:

| Field | Value |
|---|---|
| `evaluated` / `total` | **0 / 40** |
| `remaining` | 40 |
| `status` | `NOT_STARTED — Gemini quota limited` |
| `accuracy` | `null` — rendered in the UI as *withheld* |
| `results` (CORRECT / PARTIAL / INCORRECT / UNABLE_TO_EVALUATE) | 0 / 0 / 0 / 0 |
| `stored_records` | 3 |
| `invalidated` | 1 — `CASE-001` |
| `failed_calls` | 2 — `CASE-002`, `CASE-003` |

### What is on disk, and why

| Record set | State | Why it is kept |
|---|---|---|
| `evaluation_results.prompt-1.0.0.archive.json` | 27 records, prompt v1.0.0 | Retained for auditability. Superseded by a prompt revision, so not official — but not deleted either |
| `evaluation_results.json` → `CASE-001` | completed, prompt **1.2.0**, `invalidated: true`, `requires_rerun: true` | Produced under a prompt version that was subsequently corrected. Kept as evidence of what actually happened; excluded from every metric |
| `evaluation_results.json` → `CASE-002`, `CASE-003` | `evaluation_status: failed`, quota error | Failed calls are recorded, not hidden. Counted as attempts, never as evaluations |
| Any record under prompt **1.2.1** | none | The current prompt version has not been run against the dataset |

`is_official = succeeded and not invalidated`. Neither an invalidated record nor a failed call
can enter a result bucket or an accuracy denominator, and
`tests/test_dashboard.py::test_invalidated_records_cannot_enter_the_accuracy_denominator` asserts
it structurally so a future edit cannot quietly reintroduce the problem.

### Why coverage is incomplete

The Gemini free tier caps the configured project at **20 `generateContent` requests per day** for
`gemini-3.6-flash` (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, metric
`generativelanguage.googleapis.com/generate_content_free_tier_requests`), on a rolling 24-hour
window. The quota is scoped **per project, not per key**, so issuing a new key does not reset it.
A 40-case batch does not fit inside it, and the batch that was attempted exhausted it partway
through.

**Live Gemini evaluation is currently incomplete because the configured free-tier project/model
quota is limited.**

### Why accuracy is withheld rather than extrapolated

Reporting an accuracy computed over one or three cases as a "40-case result" would be the single
most misleading thing this project could do, so it is prevented by construction:
`ai_evaluation_summary` returns `accuracy: None` unless `coverage_complete` — every case in the
dataset has an official record — and the UI prints the literal word *withheld*. The withholding is
a function of coverage, not a permanent refusal; `test_complete_coverage_releases_accuracy`
asserts the figure appears as soon as coverage is genuinely complete.

## 9. Verifying these numbers

```bash
python -m backend.scripts.verify_evaluation_integrity
```

Read-only. It recomputes the official / invalidated / failed classification directly from the
files on disk and asserts field-by-field equality with what the dashboard service reports, checks
the archive is intact, checks no v1.2.1 record has appeared, and checks neither payload contains a
credential token. **33 of 33 checks pass.**

```bash
python -m pytest -v                                       # 532 passed, 9 deselected
python -m backend.app.rules.cli --all --check-expected     # the golden comparison
python -m backend.scripts.build_evaluation_reports         # reports, from stored results only
```

`build_evaluation_reports` regenerates `reports/ai_evaluation.{json,md}`,
`reports/case_evaluation_matrix.csv` and the review queue purely from
`data/evaluation_results.json`. It spends no quota and cannot produce a figure that is not in the
stored records.

## 10. What would complete this evaluation

Two things, neither of which can be manufactured:

1. **Quota.** Either a paid tier, a different project, or 40 requests spread across several days,
   plus explicit authorisation to spend it. `CASE-001` needs re-running under prompt 1.2.1; the
   other 39 have never completed.
2. **Five genuine human corrections**, produced by a person actually reviewing diagnoses and
   disagreeing with them.

Until both exist, the honest report is the one the dashboard already gives: the deterministic
engine is validated, and the AI evaluation has not been run.
