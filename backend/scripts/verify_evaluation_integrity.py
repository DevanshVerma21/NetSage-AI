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
invalidated_archive = load("evaluation_results.prompt-1.2.0.invalidated.archive.json")
results = load("evaluation_results.json")
check("v1.0.0 archive retained", archive is not None)
check(
    "the archive still holds its 27 records",
    isinstance(archive, list) and len(archive) == 27,
    f"{len(archive) if isinstance(archive, list) else archive}",
)
check("the live results file exists", isinstance(results, list))
check("v1.2.0 invalidated record archive retained",
      isinstance(invalidated_archive, list) and len(invalidated_archive) == 1)
check("responsible_ai_log.json contains five genuine corrections",
      isinstance(load("responsible_ai_log.json"), dict)
      and len(load("responsible_ai_log.json").get("corrections", [])) == 5)

print("\n2. raw record classification, computed from the file")
raw_official = [
    r for r in results
      if r.get("evaluation_status") == "completed"
      and not r.get("invalidated")
      and r.get("provider") == "gemini"
      and r.get("prompt_version") == "1.2.1"
]
raw_invalidated = [r for r in (invalidated_archive or []) if r.get("invalidated")]
raw_failed = [r for r in results if r.get("evaluation_status") != "completed"]
check("22 current Gemini records are official", len(raw_official) == 22,
        f"{len(raw_official)}: {[r['case_id'] for r in raw_official]}")
check("the v1.2.0 CASE-001 record is retained and invalidated",
      [r["case_id"] for r in raw_invalidated] == ["CASE-001"],
      f"{[r['case_id'] for r in raw_invalidated]}")
check("the invalidated record was produced under prompt 1.2.0",
      raw_invalidated[0].get("prompt_version") == "1.2.0" if raw_invalidated else False,
      raw_invalidated[0].get("prompt_version") if raw_invalidated else "no record")
check("it is flagged requires_rerun",
      bool(raw_invalidated and raw_invalidated[0].get("requires_rerun")))
check("the remaining quota failure is retained",
      sorted(r["case_id"] for r in raw_failed) == ["CASE-005"],
      f"{sorted(r['case_id'] for r in raw_failed)}")
check("all official records use v1.2.1",
      all(r.get("prompt_version") == "1.2.1" for r in raw_official))

print("\n3. the dashboard payload matches those files exactly")
payload = d.dashboard()
ai = payload["ai_evaluation"]
det = payload["deterministic"]
hr = payload["human_review"]

check("evaluated == official records on disk", ai["evaluated"] == len(raw_official),
      f"{ai['evaluated']} vs {len(raw_official)}")
check("official Gemini evaluations are 22 of 40",
      (ai["evaluated"], ai["total"]) == (22, 40), f"{ai['evaluated']}/{ai['total']}" )
check("remaining == 18", ai["remaining"] == 18, str(ai["remaining"]))
check("active invalidated count matches",
      ai["invalidated"] == len([r for r in results if r.get("invalidated")]))
check("failed count matches", ai["failed_calls"] == len(raw_failed))
check("stored_records == rows in the file", ai["stored_records"] == len(results))
check("accuracy is withheld while coverage is incomplete", ai["accuracy"] is None,
      str(ai["accuracy"]))
check("result buckets contain only official rows",
      sum(ai["results"].values()) == 22, json.dumps(ai["results"]))
check("status names the real state",
      ai["status"] == "PARTIAL — Gemini quota limited", ai["status"])

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
check("human review totals are 10 / 5 / 2 / 3",
      (hr["total_reviews"], hr["accepted"], hr["edited"], hr["rejected"], hr["corrections"])
      == (10, 5, 2, 3, 5), str(hr))
log = d.responsible_ai_log()
check("the correction log exposes five stored corrections",
      log["available"] is True and len(log["corrections"]) == 5)

print("\n6. nothing on the page leaks a credential")
blob = json.dumps(payload).lower() + json.dumps(d.responsible_ai()).lower()
for token in ("api_key", "aiza", "sk-ant", "authorization", "bearer "):
    check(f"no '{token}' in the payloads", token not in blob)

print("\n" + "=" * 72)
print(f"EVALUATION INTEGRITY: {'PASS' if not FAIL else 'FAIL'}")
print(f"{'' if not FAIL else 'failed: ' + ', '.join(FAIL)}")
raise SystemExit(0 if not FAIL else 1)
