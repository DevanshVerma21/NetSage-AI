# Evaluation methodology — Phase 6

How the 40-case Gemini evaluation decides whether a diagnosis was right. Every rule here is
mechanical and was fixed **before** the first batch ran. The implementation is
[backend/app/services/evaluation.py](../backend/app/services/evaluation.py).

## Integrity rules

- **The model never grades itself.** Gemini is asked for a diagnosis and nothing else. Every
  comparison below is a set or substring operation performed in Python against
  `data/cases.json`.
- **Ground truth is read-only.** `expected_rule_ids`, `expected_root_cause_keywords`,
  `osi_layer` and `concept_tag` were fixed in Phase 5 and were not edited after any AI output
  was seen. No script in Phase 6 writes to `data/cases.json`.
- **Thresholds are fixed in advance.** The two constants below are the only tunable numbers,
  and they are stated here so a reader can check they were not moved to flatter the score.
- **Nothing is dropped.** A case whose API call fails is stored with
  `evaluation_status = "failed"`, counted in every total, and listed in the report.
- **Failed citations survive.** The evidence verifier's verdict is copied onto each citation;
  a citation that could not be located keeps its original text plus the reason it failed.

## The four comparisons

For each case that produced a diagnosis:

| Dimension | How it is measured |
| --- | --- |
| **A. Rule agreement** | True when at least one of the case's `expected_rule_ids` appears in the reconciler's `matched_rule_ids` — that is, a deterministic finding whose category equals the AI's category. The reconciler is the existing Phase 2 component; Phase 6 does not reimplement it. |
| **B. Root-cause keyword agreement** | Each `expected_root_cause_keywords` entry is normalised (whitespace collapsed, case folded) and searched for in the normalised concatenation of `root_cause`, `notes_for_reviewer`, and each fix step's `rationale` and `cli_commands`. `keyword_hit_rate` = matched / total. Agreement is `hit_rate >= 0.5`. |
| **C. OSI agreement** | `ai.osi_layer == case.osi_layer`. Exact match, no partial credit. |
| **D. Category agreement** | `ai.category == case.concept_tag`. Exact match. |

The keyword haystack deliberately extends past `root_cause`: a model that names the fault only
in its remediation (`no ip helper-address`) has still identified it. It never extends outside
the model's own diagnosis.

## Thresholds

```
KEYWORD_RATE_FOR_CORRECT = 0.5    # at least half the ground-truth keywords for CORRECT
KEYWORD_RATE_FOR_PARTIAL = 0.25   # below this, with the category also wrong, it is INCORRECT
```

## Classification

Evaluated in this order; the first matching rule wins.

1. **UNABLE_TO_EVALUATE** — the Gemini call failed permanently, *or* the model set
   `insufficient_evidence = true` and asserted no root cause. Declining honestly is correct
   behaviour under this system's rules, so it is not scored as a wrong answer; it is also not
   a right one, so it is excluded from the agreement denominators.
2. **CORRECT** — all of: category matches, OSI layer matches, `keyword_hit_rate >= 0.5`, rule
   agreement holds, *every* expected rule was corroborated (no secondary finding missed), and
   evidence integrity is not `failed`. A diagnosis that is right but unsubstantiated is not
   counted as correct.
3. **INCORRECT** — the category does not match *and* `keyword_hit_rate < 0.25`. The model was
   looking at a different fault.
4. **INCORRECT** — evidence integrity `failed` *and* the category does not match: nothing in
   the diagnosis is both right and supported.
5. **PARTIAL** — everything else. Typically: the primary fault identified but a secondary
   finding missed, the right fault at the wrong OSI layer, or a partial keyword overlap. The
   report records exactly which conditions were unmet in `classification_reason`.

`PARTIAL` is explicitly the verdict for "identified the primary fault, missed a secondary
one", per the phase specification.

## What the verdict is *not*

- It is not a measure of whether the fix steps would work. That is the fix simulator's job and
  is out of scope here.
- It is not a human judgement. A human reviewer can and does disagree with these labels; that
  disagreement is recorded separately in `data/reviews.json` and
  `data/responsible_ai_log.json`, and never overwrites the mechanical result.
- `CORRECT` does not mean safe to apply. Every diagnosis in this system remains
  `awaiting_human_review` with `applied = false` until a human decides otherwise.

## Derived metrics

- **Evidence**: per-case integrity (`passed` / `partial` / `failed`) plus corpus-wide total,
  verified and failed citation counts and a verification rate.
- **Confidence**: the distribution of `model_confidence` (what Gemini claimed) against
  `effective_confidence` (what the deterministic caps allowed), plus the cross-tabulations
  that matter for responsible AI — high-confidence incorrect, high-confidence partial,
  low-confidence correct, medium-confidence correct.
- **Reconciliation**: the existing five-state distribution (`agree`, `partial`, `ai_only`,
  `rules_only`, `conflict`), unmodified.

## Reproducing

```bash
python -m backend.scripts.evaluate_all_cases --dry-run   # config check, no API calls
python -m backend.scripts.evaluate_all_cases             # one Gemini call per case
python -m backend.scripts.build_evaluation_reports       # metrics, reports, review queue
```

The reports are regenerated purely from `data/evaluation_results.json`, so they can be rebuilt
at any time without spending quota, and cannot contain a figure that is not in the stored
results.
