# NetSage AI — Known Limitations

Everything on this list is a real constraint on what this prototype can be said to do. None of
it is hidden in the product: the dashboard and `/responsible-ai` report the same facts from
stored data, and where a number is unmeasured the interface says so rather than estimating.

Severities: **high** — materially limits what may be claimed · **medium** — bounds the scope ·
**low** — worth knowing.

---

## 1. Gemini free-tier quota — *high*

The configured project is capped at **20 `generateContent` requests per day** for
`gemini-3.6-flash`: quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, metric
`generativelanguage.googleapis.com/generate_content_free_tier_requests`, rolling 24-hour window.

The cap is scoped **per project, not per key**, so issuing a new API key does not reset it. A
40-case batch does not fit inside a single day's allowance, and the attempted batch exhausted the
quota partway through.

**Consequence:** live AI evaluation cannot be completed on the current tier without either a
paid tier, a different project, or the batch spread across several days.

## 2. Live AI evaluation is incomplete — *high*

**Live Gemini evaluation is currently incomplete because the configured free-tier project/model
quota is limited.**

**Official Gemini evaluations: 0 of 40.** There is no AI accuracy figure for this system, and the
absence is not a stand-in for a good one — it is unmeasured.

What exists on disk is retained rather than tidied away: 27 archived records from prompt v1.0.0,
one `CASE-001` record produced under prompt v1.2.0 and marked `invalidated` / `requires_rerun`,
and two failed quota-limited calls for `CASE-002` and `CASE-003`. None of them is official. No
record has been fabricated, no invalidated or failed record has been promoted, and no accuracy has
been extrapolated from partial coverage.

`accuracy` is returned as `null` and rendered as the literal word *withheld* until every case has
an official record. The withholding is a function of coverage, not a permanent refusal.

**Consequence:** nothing in this repository supports a claim about how well the AI diagnoses
faults. The deterministic results (§ below and in [`EVALUATION.md`](EVALUATION.md)) are unaffected,
because they involve no model call.

## 3. No real device execution — *high*

There is no device connectivity anywhere in the codebase: no SSH, Telnet, Netmiko, paramiko, or
scrapli, and no `subprocess`, `os.system`, `eval`, `exec`, or `shell=True` in `backend/app/`. No
endpoint accepts a command, a mutation, or a device address from a client.

This is a deliberate design boundary, not an unfinished feature — but it is still a limitation on
what the system can verify.

**Consequence:** a fix is never applied to anything. It mutates a deep copy of the structured lab
model, and verification re-runs the deterministic engine over that copy. Every fix run carries
`execution_scope: "simulated_lab_model"` and the disclaimer *"Verified against simulated lab model
— not executed on physical hardware or Packet Tracer."* A fix that verifies here has not been
shown to work on hardware.

## 4. The lab is simulated — *high*

The topologies are structured `LabState` objects with hand-written Cisco `show` output. They are
Packet Tracer–*style*, not Packet Tracer captures, and no case claims otherwise: all 40 carry
`source_label: "simulated-lab"` and a test asserts it.

The model reads the `show` text; the rule engine reads the structure. A test
(`test_show_output_consistency.py`) requires every fact in the structure to be visible in the text
so the two cannot drift — but both were authored by the same hand, so neither is independent
evidence about real devices.

**Consequence:** the show output is realistic but not real. Behaviours a real device exhibits and a
hand-written capture omits — timing, counters, log noise, platform quirks, partial output — are
absent, and a model that copes here has not been shown to cope with a real capture.

## 5. The dataset is self-authored — *high*

All 40 cases, and all of their ground truth, were written by the project author. The dataset is
not a sample of real production incidents, and its fault distribution reflects the problem
statement's syllabus rather than any observed frequency.

The integrity discipline that makes it usable is stated plainly because it is a discipline, not a
mechanism: `expected_rule_ids`, `expected_root_cause_keywords`, `osi_layer` and `concept_tag` were
fixed when each case was authored and have not been edited after seeing any model output, and no
evaluation script writes to `data/cases.json`.

**Consequence:** results are measurements against this dataset only. There is a structural risk
that a self-authored dataset favours the rules written alongside it, and this project cannot rule
that out from the inside.

## 6. Rule coverage is bounded — *medium*

15 rules, of which 6 are the mandatory checks named in the problem statement. They cover
addressing, gateways, masks, interface state, VLANs and trunks, routing, overlapping subnets, DHCP,
DNS, ACLs, NAT, wireless isolation, and SVIs.

That is a deliberately finite list. Spanning tree, HSRP/VRRP, routing-protocol adjacency and
metrics, QoS, MTU and fragmentation, port security, IPv6, MAC-layer faults, and physical-layer
degradation are **not** modelled.

The engine is also whole-state analysis rather than fault localisation: it reports what it can
prove from the structure, so a fault outside the 15 rules produces no deterministic finding at all
— and then the AI proposal has nothing to be reconciled against, which the reconciler reports as
`ai_only` and the capping table treats as a reason to lower confidence.

**Consequence:** "the rule engine found nothing" means "no modelled fault is present", not "the
network is healthy".

## 7. Citation verification is not proof of correctness — *high*

The evidence verifier proves that a quoted excerpt genuinely appears in the output of the command
it names. That is all it proves.

A model can quote entirely real output and still draw the wrong conclusion from it; it can cite the
correct lines for an incorrect root cause; it can cite a true fact that is irrelevant to the
symptom. `evidence_integrity: passed` therefore means *"nothing was fabricated"*, never *"the
diagnosis is right"*.

**Consequence:** verification narrows the failure modes to misreading rather than invention. It
does not remove the need for the human gate, which is why the gate is mandatory rather than
advisory.

## 8. Model output varies between runs — *medium*

The Gemini providers are called with structured output and a fixed, hash-pinned prompt, but a
language model is not a deterministic function. The same case can produce a differently worded root
cause, a different citation set, or a different self-reported confidence on two consecutive runs,
and a diagnosis that grades `CORRECT` once may grade `PARTIAL` on a repeat.

Nothing in this project measures that variance: there has been no repeated-run study, and the quota
in §1 is precisely what makes one impractical. Each record does store `provider`, `model`,
`prompt_version` and `prompt_sha256`, so a result can at least be attributed to an exact prompt and
model.

**Consequence:** any single-run AI figure — including a future completed 40-case run — is one
sample, not a stable performance measurement, and should be reported that way.

For repeatable demonstration there is `LLM_PROVIDER=mock`: an offline provider that derives its
diagnosis from the rule findings and quotes real lines from the supplied output. It is deterministic
and stamps `provider: "mock"` on every record so a mock answer can never be mistaken for a model
answer — but it is a fixture, not a model, and proves nothing about model quality.

## 9. There is no authentication and no identity — *medium*

The API has no authentication, no authorisation, and no user accounts. A recorded human verdict
carries a reviewer name as a **self-declared string**; nothing verifies who submitted it.

This is appropriate for a local single-operator prototype and is stated rather than fixed because
adding authentication was out of scope. It does bound what the audit trail means.

**Consequence:** the audit trail is tamper-evident only in the weak sense that reviews are
write-once (a second review of the same diagnosis returns `409`). It is not attributable, and it is
not an access-control boundary. The API should not be exposed beyond localhost as it stands.

## 10. Human review is currently incomplete — *high*

**0 recorded reviews.** The Responsible AI requirement is **5 genuine human corrections** — an
`edited` or `rejected` verdict with a reason code — and there are none.

`data/responsible_ai_log.json` does not exist, so the correction log renders an empty state rather
than illustrative examples, and the dashboard reports *"Human review data incomplete"*. The
requirement is displayed as a target throughout and never as an achievement.

No review, correction, reason code or lesson has been fabricated to fill the gap. Collecting them
requires a person working through `python -m backend.scripts.review_candidates` in a terminal and
genuinely disagreeing with diagnoses; it cannot be generated.

**Consequence:** the human-in-the-loop mechanism is implemented, tested and server-enforced, but it
has not been exercised at the required volume. The gate's *behaviour* is verified by tests and by
the end-to-end script; its *use* is not yet evidenced by data.

---

## What is not limited

For balance, the deterministic half is complete and validated, and does not depend on any of the
above except §5 and §6:

| Measure | Value |
|---|---|
| Cases | 40 |
| Rules | 15 (6 mandatory + 9 optional) |
| Golden expected-vs-fired | **PASS**, 0 mismatches |
| Rule pass rate | **1.0** |
| Offline test suite | **532 passed** (9 live tests deselected by default) |
| Dashboard-vs-files integrity | **33/33 checks pass** |

That result involves no model call and would be unchanged if no provider were ever configured. It
is a statement about the rule engine, not about the AI.

Details: [`EVALUATION.md`](EVALUATION.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md).
