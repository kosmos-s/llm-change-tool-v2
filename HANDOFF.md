# LLM Change Tool v2 — handoff
Claude continuation (2026-10-18): read CLAUDE.md and docs/claude-handoff.md.
Local inventory and final development/holdout selection artifacts already exist;
check their current state before repeating preparation. See the continuation note
for local paths, historical verification limits and the next human-review steps.

Updated: 2026-10-19 (v0.1.11 released). Older sections keep their original dates. Inspect current main and open PRs before modifying.

## Latest direction: proceed independently while company reply is pending
User reports no company reply for about a week and authorizes proceeding with
provisional internal criteria, revisable later. Company confirmation is NOT a
prerequisite for internal development, offline inventory, sampling or human
review. See docs/independent-experiment-plan.md: internal target scene F1 >=0.85
(unmeasured/aspirational), val development up to 50 and separate test holdout up
to 200, frozen by seed/fingerprint with quality/split guards. This is not a
company target or paid-call authorization. Keep all actual predictions locally
so changed aggregation criteria can be evaluated again. No paid API, company
server or original edits. Main merge and release need an explicit user request
each time (v0.1.11 was one such request on 2026-10-19). Actual model retraining still
requires code/weights/environment; do not substitute Mock metrics for it.

## Follow-up branch (2026-10-15, released in v0.1.11)
Items 1–3 below were reproduced on main 0b63f14 and fixed on
fix/handoff-review-and-budget, merged as PR #11. See docs/handoff-fixes-20261015.md for verification.
Windows/Python 3.11 offline verification: 154 pytest passed, Ruff/format,
compileall, index secret/data scan, self-test and offscreen GUI/worker smoke passed.
Original contract preserved; added working rules merged. No paid API call or
company-source modification is authorized by this follow-up.
New default is detailed; legacy core pilot semantics remain explicit. Production
requires low-confidence review even for legacy comparisons. Schema 7 adds an
audited image-reservation override so existing jobs can resume without rewriting
their frozen settings. Back up before opening; older binaries cannot open v7 DBs.
Corporate references remain outside the repository. The latest user decisions
below supersede historical pending statements. Mock checks do not establish real accuracy.

## User decisions and evaluation follow-up (2026-10-15, released in v0.1.11)
User permits all provided files as candidates, subject to quality/dedup/split
checks. English reasons are optional; automatic paid translation is not needed.
User expects F1 and authorizes defining internal criteria. scene-f1-v1 uses OR
of arti/tree/fore/farm/water as the primary binary scene-change F1; major-label
micro F1 remains secondary. This is an internal working policy, not confirmation
of the company's official metric or target. See docs/evaluation-policy.md.
Automatic evaluation of actual baseline/retrained predictions on the same fixed
human reference and manual image/count audit are supported. Actual model
training is external; no training code/weights were found in the provided folder.
Do not create real human truth by auto-approving source/Mock labels. Real Mock
pilots remain drafts pending actual human review. No paid production is approved.
Offline checks: 161 pytest passed; final affected checks 15 passed; Ruff/format,
compileall, self-test and GUI/worker smoke passed. A separate real-file 20-item
Mock project has 20 DRAFT / 0 human-complete reviews and a correctly blocked
Export Gate; reopen/backup/restore and 80 original-file hashes checked.
See docs/evaluation-verification-20261015.md. This is not measured model gain.

## Purpose and constraints
Repository: https://github.com/kosmos-s/llm-change-tool-v2
Two aerial images T1/T2 + original JSON → LLM classification → comparison → human review → separate corrected JSON.
Python 3.11, PySide6, SQLite, SQLAlchemy, Pydantic, PyInstaller. Local-first; no NAS/server requirement.
School pays API costs. Program demonstration and results presentation are the agreed handoff approach; company deployment/integration is not established.
v1 kosmos-s/llm-change-auto is reference only; do not revert to Streamlit/CSV.

## Last verified release
v0.1.11 (2026-10-19, user request), PR #11 merged, merge SHA ce52d2065e8ea09c3c98fea9def6a63e199ae765.
Adds blind (independent) review mode on top of the 2026-10-15 review/budget/scene-F1 fixes. DB schema stays 7.
PR checks passed on Windows/Linux including the Portable build. The release workflow built
and verified the frozen EXE (self-test, GUI smoke) and published the portable ZIP and SHA256:
https://github.com/kosmos-s/llm-change-tool-v2/releases/tag/v0.1.11
Local tests: 171 pytest passed, Ruff/format, compileall, secret scan, self-test, GUI/worker smoke.
Human-complete reviews of real images: still 0. This does not establish paid-API accuracy or model gain.

Previous: v0.1.10, PR #10, merge SHA 0b63f14b589c200196ebf4ca7522056a634e71ce.

## Historical implementation scope (2026-10-10; items 1–3 fixed in v0.1.11)
First reproduce against current code; skip already-fixed findings.
1. arti_other_detail can remain after arti_other is cleared. Fix effective review/export data without changing original JSON.
2. core low-confidence behavior: all-zero labels, confidence=0.1, review_required=false matching original labels could become AUTO_KEEP. Review policy intentionally differed from detailed policy. Design explicit review behavior and verify required-review counts, existing jobs and Gate compatibility.
3. Fixed 20,000 input-token reservation can underestimate larger-image requests. Account for model/image dimensions/detail, prompt/schema, output allowance, retries and concurrent reservations. Unknown prices must not silently be zero. Distinguish estimates from a provider-enforced billing cap. Test offline.
4. English reasons are not automatically translated; stale English can be cleared after edits. User has confirmed English is optional. Do not add paid translation automatically.
5. Company model training and area annotation/IoU evaluation are not a complete included pipeline. Do not claim label comparison metrics prove retrained-model gains.

For new coding tasks: add regression tests, run relevant/full required checks and verify the affected end-to-end flow with Mock. Commit on a separate branch and open a PR when requested. Main merge/release and paid API calls need an explicit user request.

## Pending company decisions (no answer as of last conversation)
Official F1 vs F2 metric, positive class, evaluation data/performer;
3,000-sample selection scope and split; meaning of FN/FP and filename suffixes;
final development/delivery scope and timeline.
Historical document mismatch: proposal F1 0.80→0.85; company PDF F2 0.80→0.85 and other F1 references. Verify source pages when files available.
Internal work proceeds under the provisional protocol above while these remain
pending. Paid 3,000-sample processing still requires explicit direction; do not
declare a company target achieved from internal or Mock results.

## References to provide locally
- Company PDF and university proposal DOCX.
- Label construction guideline; latest policy 26.03.24 excludes road marks alone.
- Review-tool usage guideline: may contain credentials. Do not echo credentials or commit it.
- bizlogic.zip: inspect statically only. Prior inspection found unrelated mining executables; do not execute them and do not infer compromise from their mere presence.
- dataset_sample.z01 + dataset_sample.z02 + dataset_sample.zip: multipart archive; all three must be in the same folder. Unpack using software supporting split ZIP. Do not treat a single piece as a complete dataset.
- Screenshots are supporting UI evidence only.
Reference files are not automatically transferred from ChatGPT to Codex.

## User checks after fixes
Backup project. Process 10–20 samples end to end on Windows. Check real image judgment and exported labels manually.
Proceed with internal inventory, sample selection, review and experiment records
without waiting for company decisions. Paid production needs separate direction.

