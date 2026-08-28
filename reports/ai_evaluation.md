# NetSage AI — 40-case Gemini evaluation

Every figure below is calculated from `data/evaluation_results.json`. Nothing is hard-coded; regenerate with `python -m backend.scripts.build_evaluation_reports`.

* provider / model: **gemini** / **gemini-3.6-flash**
* prompt version: 1.2.1
* cases evaluated: **23** — 22 successful, 1 failed
* latency: min 21879 ms · median 36359 ms · max 174580 ms

The AI never graded itself: every comparison in this report is a mechanical set/string operation against `data/cases.json`, which was not modified after the batch ran. See `docs/evaluation_methodology.md`.

## 1. AI vs ground truth

| Result | Cases | Share |
| --- | --- | --- |
| CORRECT | 3 | 13% |
| PARTIAL | 19 | 83% |
| INCORRECT | 0 | 0% |
| UNABLE_TO_EVALUATE | 1 | 4% |

## 2. Agreement dimensions

Measured over the 22 case(s) that produced a scoreable diagnosis.

| Dimension | Agreed |
| --- | --- |
| Rule agreement (an expected rule corroborated) | 22 (100%) |
| Root-cause keyword agreement (≥50% of keywords) | 20 (91%) |
| OSI layer agreement | 21 (95%) |
| Category agreement | 22 (100%) |
| Mean keyword hit rate | 57% |

## 3. Evidence integrity

| Integrity | Cases |
| --- | --- |
| passed | 4 |
| partial | 0 |
| failed | 18 |

Citations: **67** total · 12 verified · 55 failed · verification rate **17.9%**.

Failed citations are stored verbatim in the results file. None was overwritten, repaired or discarded.

## 4. Confidence

| Band | Model confidence | Effective confidence |
| --- | --- | --- |
| high | 22 | 4 |
| medium | 0 | 0 |
| low | 0 | 18 |

* capped by the deterministic checks: **18** case(s) (18 of them claimed HIGH and were reduced)
* high-confidence INCORRECT: **0**
* high-confidence PARTIAL: **1**
* low-confidence CORRECT: **0**
* medium-confidence CORRECT: **0**

## 5. Reconciliation against the rule engine

| Status | Cases |
| --- | --- |
| agree | 22 |
| partial | 0 |
| ai_only | 0 |
| rules_only | 0 |
| conflict | 0 |

## 6. Result by category

| Category | Total | CORRECT | PARTIAL | INCORRECT | UNABLE_TO_EVALUATE |
| --- | --- | --- | --- | --- | --- |
| ACL | 3 | 1 | 2 | 0 | 0 |
| DHCP | 3 | 0 | 3 | 0 | 0 |
| DNS | 2 | 0 | 2 | 0 | 0 |
| GATEWAY | 2 | 0 | 2 | 0 | 0 |
| INTERFACE_CONFIG | 2 | 0 | 2 | 0 | 0 |
| NAT | 2 | 0 | 2 | 0 | 0 |
| ROUTING | 2 | 0 | 2 | 0 | 0 |
| VLAN | 5 | 0 | 4 | 0 | 1 |
| WIRELESS | 2 | 2 | 0 | 0 | 0 |

## 7. Failed evaluations

| Case | Error | Attempts | Message |
| --- | --- | --- | --- |
| CASE-005 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |

## 8. Per-case matrix

| Case | Category | Result | Model conf. | Effective conf. | Evidence | Reconciliation |
| --- | --- | --- | --- | --- | --- | --- |
| CASE-001 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-002 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-003 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-004 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-005 | VLAN | UNABLE_TO_EVALUATE |  |  |  |  |
| CASE-006 | GATEWAY | PARTIAL | high | low | failed | agree |
| CASE-007 | GATEWAY | PARTIAL | high | low | failed | agree |
| CASE-011 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-012 | DHCP | PARTIAL | high | high | passed | agree |
| CASE-013 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-016 | DNS | PARTIAL | high | low | failed | agree |
| CASE-017 | DNS | PARTIAL | high | low | failed | agree |
| CASE-020 | ROUTING | PARTIAL | high | low | failed | agree |
| CASE-021 | ROUTING | PARTIAL | high | low | failed | agree |
| CASE-025 | ACL | PARTIAL | high | low | failed | agree |
| CASE-026 | ACL | CORRECT | high | high | passed | agree |
| CASE-027 | ACL | PARTIAL | high | low | failed | agree |
| CASE-029 | NAT | PARTIAL | high | low | failed | agree |
| CASE-030 | NAT | PARTIAL | high | low | failed | agree |
| CASE-033 | WIRELESS | CORRECT | high | high | passed | agree |
| CASE-034 | WIRELESS | CORRECT | high | high | passed | agree |
| CASE-037 | INTERFACE_CONFIG | PARTIAL | high | low | failed | agree |
| CASE-038 | INTERFACE_CONFIG | PARTIAL | high | low | failed | agree |

Full per-case detail, including every citation and the classification reason, is in `data/evaluation_results.json`; the machine-readable summary is in `reports/ai_evaluation.json` and the flat matrix in `reports/case_evaluation_matrix.csv`.
