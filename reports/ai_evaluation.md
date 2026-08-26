# NetSage AI — 40-case Gemini evaluation

Every figure below is calculated from `data/evaluation_results.json`. Nothing is hard-coded; regenerate with `python -m backend.scripts.build_evaluation_reports`.

* provider / model: **gemini** / **gemini-3.6-flash**
* prompt version: 1.0.0
* cases evaluated: **27** — 21 successful, 6 failed
* latency: min 17623 ms · median 23528 ms · max 84531 ms

The AI never graded itself: every comparison in this report is a mechanical set/string operation against `data/cases.json`, which was not modified after the batch ran. See `docs/evaluation_methodology.md`.

## 1. AI vs ground truth

| Result | Cases | Share |
| --- | --- | --- |
| CORRECT | 1 | 4% |
| PARTIAL | 17 | 63% |
| INCORRECT | 3 | 11% |
| UNABLE_TO_EVALUATE | 6 | 22% |

## 2. Agreement dimensions

Measured over the 21 case(s) that produced a scoreable diagnosis.

| Dimension | Agreed |
| --- | --- |
| Rule agreement (an expected rule corroborated) | 20 (95%) |
| Root-cause keyword agreement (≥50% of keywords) | 19 (90%) |
| OSI layer agreement | 20 (95%) |
| Category agreement | 18 (86%) |
| Mean keyword hit rate | 58% |

## 3. Evidence integrity

| Integrity | Cases |
| --- | --- |
| passed | 2 |
| partial | 0 |
| failed | 19 |

Citations: **68** total · 8 verified · 60 failed · verification rate **11.8%**.

Failed citations are stored verbatim in the results file. None was overwritten, repaired or discarded.

## 4. Confidence

| Band | Model confidence | Effective confidence |
| --- | --- | --- |
| high | 21 | 2 |
| medium | 0 | 0 |
| low | 0 | 19 |

* capped by the deterministic checks: **19** case(s) (19 of them claimed HIGH and were reduced)
* high-confidence INCORRECT: **0**
* high-confidence PARTIAL: **1**
* low-confidence CORRECT: **0**
* medium-confidence CORRECT: **0**

## 5. Reconciliation against the rule engine

| Status | Cases |
| --- | --- |
| agree | 20 |
| partial | 1 |
| ai_only | 0 |
| rules_only | 0 |
| conflict | 0 |

## 6. Result by category

| Category | Total | CORRECT | PARTIAL | INCORRECT | UNABLE_TO_EVALUATE |
| --- | --- | --- | --- | --- | --- |
| ACL | 3 | 0 | 0 | 0 | 3 |
| DHCP | 5 | 0 | 5 | 0 | 0 |
| DNS | 4 | 1 | 2 | 1 | 0 |
| GATEWAY | 5 | 0 | 4 | 1 | 0 |
| ROUTING | 5 | 0 | 2 | 0 | 3 |
| VLAN | 5 | 0 | 4 | 1 | 0 |

## 7. Failed evaluations

| Case | Error | Attempts | Message |
| --- | --- | --- | --- |
| CASE-020 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |
| CASE-021 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |
| CASE-024 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |
| CASE-025 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |
| CASE-026 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |
| CASE-027 | ProviderError | 1 | Gemini request failed for model 'gemini-3.6-flash' after 4 attempt(s): ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded you |

## 8. Per-case matrix

| Case | Category | Result | Model conf. | Effective conf. | Evidence | Reconciliation |
| --- | --- | --- | --- | --- | --- | --- |
| CASE-001 | VLAN | PARTIAL | high | high | passed | agree |
| CASE-002 | VLAN | INCORRECT | high | low | failed | agree |
| CASE-003 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-004 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-005 | VLAN | PARTIAL | high | low | failed | agree |
| CASE-006 | GATEWAY | PARTIAL | high | low | failed | agree |
| CASE-007 | GATEWAY | PARTIAL | high | low | failed | agree |
| CASE-008 | GATEWAY | PARTIAL | high | low | failed | agree |
| CASE-009 | GATEWAY | PARTIAL | high | low | failed | agree |
| CASE-010 | GATEWAY | INCORRECT | high | low | failed | partial |
| CASE-011 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-012 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-013 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-014 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-015 | DHCP | PARTIAL | high | low | failed | agree |
| CASE-016 | DNS | CORRECT | high | high | passed | agree |
| CASE-017 | DNS | PARTIAL | high | low | failed | agree |
| CASE-018 | DNS | PARTIAL | high | low | failed | agree |
| CASE-019 | DNS | INCORRECT | high | low | failed | agree |
| CASE-020 | ROUTING | UNABLE_TO_EVALUATE |  |  |  |  |
| CASE-021 | ROUTING | UNABLE_TO_EVALUATE |  |  |  |  |
| CASE-022 | ROUTING | PARTIAL | high | low | failed | agree |
| CASE-023 | ROUTING | PARTIAL | high | low | failed | agree |
| CASE-024 | ROUTING | UNABLE_TO_EVALUATE |  |  |  |  |
| CASE-025 | ACL | UNABLE_TO_EVALUATE |  |  |  |  |
| CASE-026 | ACL | UNABLE_TO_EVALUATE |  |  |  |  |
| CASE-027 | ACL | UNABLE_TO_EVALUATE |  |  |  |  |

Full per-case detail, including every citation and the classification reason, is in `data/evaluation_results.json`; the machine-readable summary is in `reports/ai_evaluation.json` and the flat matrix in `reports/case_evaluation_matrix.csv`.
