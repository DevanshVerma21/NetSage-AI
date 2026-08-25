"""Phase 3 manual smoke test, run against a real uvicorn server over HTTP.

Follows the spec's manual flow exactly: diagnose CASE-001 with the mock provider, confirm
it is awaiting human review, attempt a fix with no review (must be 409), record an ACCEPTED
review, apply the fix, print the before/after verification, and confirm the execution scope.

Records are written to a temporary directory so a smoke run never dirties data/.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8123/api"


def show(label: str, value: object) -> None:
    print(f"  {label}: {value}")


def main() -> int:
    # A copy of data/ so the smoke run's records never land in the repository. The case
    # dataset is copied in because the API reads cases.json from the same directory.
    tmp = tempfile.mkdtemp(prefix="netsage-smoke-")
    for name in ("cases.json", "cases.csv"):
        source = ROOT / "data" / name
        if source.exists():
            shutil.copy2(source, Path(tmp) / name)
    env = {**os.environ, "DATA_DIR": tmp}

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--port", "8123"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                httpx.get(f"{BASE}/health", timeout=1.0)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("server did not start")
            return 1

        print("1. GET /api/health")
        health = httpx.get(f"{BASE}/health").json()
        show("status", health["status"])
        show("cases_loaded", health["cases_loaded"])
        show("mandatory_rules", health["mandatory_rules"])
        show("provider_configured (bool only, never the key)", health["provider_configured"])
        show("execution_scope", health["execution_scope"])

        print("\n2. POST /api/diagnose  {case_id: CASE-001, provider: mock}")
        response = httpx.post(
            f"{BASE}/diagnose", json={"case_id": "CASE-001", "provider": "mock"}, timeout=60
        )
        diagnosis = response.json()
        show("http", response.status_code)
        show("status", diagnosis["status"])
        show("applied", diagnosis["applied"])
        show("rule_ids", sorted({f["rule_id"] for f in diagnosis["rule_findings"]}))

        print("\n3. POST /api/fixes/apply with no review yet")
        refused = httpx.post(
            f"{BASE}/fixes/apply", json={"diagnosis_id": diagnosis["diagnosis_id"]}
        )
        show("http", refused.status_code)
        show("detail", refused.json()["detail"])

        print("\n4. POST /api/reviews  {verdict: accepted}")
        review_response = httpx.post(
            f"{BASE}/reviews",
            json={"diagnosis_id": diagnosis["diagnosis_id"], "verdict": "accepted"},
        )
        review = review_response.json()
        show("http", review_response.status_code)
        show("agreement", review["agreement"])

        print("\n5. POST /api/fixes/apply  {review_id}")
        run_response = httpx.post(f"{BASE}/fixes/apply", json={"review_id": review["review_id"]})
        run = run_response.json()
        show("http", run_response.status_code)
        show("findings_before", len(run["findings_before"]))
        show("findings_after", len(run["findings_after"]))
        show("resolved_rule_ids", run["resolved_rule_ids"])
        show("new_rule_ids", run["new_rule_ids"])
        show("remaining_rule_ids", run["remaining_rule_ids"])
        show("verification_result", run["verification_result"])
        show("execution_scope", run["execution_scope"])
        show("disclaimer", run["disclaimer"])
        for mutation in run["mutations"]:
            state = "applied" if mutation["applied"] else "SKIPPED"
            detail = mutation["detail"] or mutation["skipped_reason"]
            print(f"    - {mutation['type']} [{mutation['rule_id']}] {state}: {detail}")

        print("\n6. re-apply the same review")
        again = httpx.post(f"{BASE}/fixes/apply", json={"review_id": review["review_id"]})
        show("http", again.status_code)
        show("detail", again.json()["detail"])
        final = httpx.get(f"{BASE}/diagnoses/{diagnosis['diagnosis_id']}").json()
        show("diagnosis.applied", final["applied"])

        print("\n7. no secret anywhere in the responses")
        blob = json.dumps([health, diagnosis, review, run]).lower()
        leaked = [name for name in ("api_key", "aiza", "sk-ant") if name in blob]
        show("leaked", leaked or "none")

        ok = (
            refused.status_code == 409
            and again.status_code == 409
            and run["verification_result"] == "verified"
            and run["execution_scope"] == "simulated_lab_model"
            and final["applied"] is True
            and not leaked
        )
        print("\nSMOKE TEST:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
