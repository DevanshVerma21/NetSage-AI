"""Phase 8 evaluation-integrity check. Read-only: it asserts, it never writes.

Every number the dashboard shows is recomputed here straight from the files on disk and
compared with what the service reports, so "the dashboard matches the backend data" is a
verified claim rather than an assumption.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.config import get_settings
from backend.app.services import dashboard as d

DATA = get_settings().data_path
FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def load(name: str):
    path = DATA / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


print("\n1. files on disk")
archive = load("evaluation_results.prompt-1.0.0.archive.json")
results = load("evaluation_results.json")
check("v1.0.0 archive retained", archive is not None)
check(
    "the archive still holds its 27 records",
    isinstance(archive, list) and len(archive) == 27,
    f"{len(archive) if isinstance(archive, list) else archive}",
)
check("the live results file exists", isinstance(results, list))
check("responsible_ai_log.json is absent (no genuine corrections yet)",
      not (DATA / "responsible_ai_log.json").exists())

print("\n2. raw record classification, computed from the file")
raw_official = [
    r for r in results
    if r.get("evaluation_status") == "completed" and not r.get("invalidated")
]
raw_invalidated = [r for r in results if r.get("invalidated")]
raw_failed = [r for r in results if r.get("evaluation_status") != "completed"]
check("no record is official", len(raw_official) == 0, f"{[r['case_id'] for r in raw_official]}")
check("the v1.2.0 CASE-001 record is retained and invalidated",
      [r["case_id"] for r in raw_invalidated] == ["CASE-001"],
      f"{[r['case_id'] for r in raw_invalidated]}")
check("the invalidated record was produced under prompt 1.2.0",
      raw_invalidated[0].get("prompt_version") == "1.2.0" if raw_invalidated else False,
      raw_invalidated[0].get("prompt_version") if raw_invalidated else "no record")
check("it is flagged requires_rerun",
      bool(raw_invalidated and raw_invalidated[0].get("requires_rerun")))
check("the two quota failures are retained",
      sorted(r["case_id"] for r in raw_failed) == ["CASE-002", "CASE-003"],
      f"{sorted(r['case_id'] for r in raw_failed)}")
check("no v1.2.1 record exists yet",
      not [r for r in results if r.get("prompt_version") == "1.2.1"])

print("\n3. the dashboard payload matches those files exactly")
payload = d.dashboard()
ai = payload["ai_evaluation"]
det = payload["deterministic"]
hr = payload["human_review"]

check("evaluated == official records on disk", ai["evaluated"] == len(raw_official),
      f"{ai['evaluated']} vs {len(raw_official)}")
check("official Gemini evaluations are 0 of 40",
      (ai["evaluated"], ai["total"]) == (0, 40), f"{ai['evaluated']}/{ai['total']}")
check("remaining == 40", ai["remaining"] == 40, str(ai["remaining"]))
check("invalidated count matches", ai["invalidated"] == len(raw_invalidated))
check("failed count matches", ai["failed_calls"] == len(raw_failed))
check("stored_records == rows in the file", ai["stored_records"] == len(results))
check("accuracy is withheld while coverage is incomplete", ai["accuracy"] is None,
      str(ai["accuracy"]))
check("no result bucket was inflated by an unofficial row",
      all(v == 0 for v in ai["results"].values()), json.dumps(ai["results"]))
check("status names the real state",
      ai["status"] == "NOT_STARTED — Gemini quota limited", ai["status"])

print("\n4. deterministic figures match the engine and the dataset")
check("40 cases", det["total_cases"] == 40, str(det["total_cases"]))
check("15 rules = 6 mandatory + 9 optional",
      (det["total_rules"], det["mandatory_rules"], det["optional_rules"]) == (15, 6, 9))
check("golden expected-vs-fired PASS", det["golden_case_result"] == "PASS")
check("rule pass rate 1.0", det["rule_pass_rate"] == 1.0, str(det["rule_pass_rate"]))

print("\n5. human review and the responsible-AI state")
from backend.app.services import review_service

stored_reviews = review_service.all_records()
check("review count matches the store", hr["total_reviews"] == len(stored_reviews),
      f"{hr['total_reviews']} vs {len(stored_reviews)}")
check("corrections are counted, not targeted",
      hr["corrections"] == len([r for r in stored_reviews if r.verdict in ("edited", "rejected")]))
check("the incomplete state is reported",
      hr["incomplete_message"] == "Human review data incomplete", str(hr["incomplete_message"]))
log = d.responsible_ai_log()
check("the correction log reports an empty state, not examples",
      log["available"] is False and log["corrections"] == [])

print("\n6. nothing on the page leaks a credential")
blob = json.dumps(payload).lower() + json.dumps(d.responsible_ai()).lower()
for token in ("api_key", "aiza", "sk-ant", "authorization", "bearer "):
    check(f"no '{token}' in the payloads", token not in blob)

print("\n" + "=" * 72)
print(f"EVALUATION INTEGRITY: {'PASS' if not FAIL else 'FAIL'}")
print(f"{'' if not FAIL else 'failed: ' + ', '.join(FAIL)}")
raise SystemExit(0 if not FAIL else 1)
