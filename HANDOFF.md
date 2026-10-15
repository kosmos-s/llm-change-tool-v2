# LLM Change Tool v2 — handoff
Updated: 2026-10-15. Historical facts below were last verified on 2026-10-10. Inspect current main and open PRs before modifying.

## Current follow-up branch (2026-10-15, unreleased)
Items 1–3 below were reproduced on main 0b63f14 and fixes are implemented on
fix/handoff-review-and-budget. See docs/handoff-fixes-20261015.md for verification.
Windows/Python 3.11 offline verification: 154 pytest passed, Ruff/format,
compileall, index secret/data scan, self-test and offscreen GUI/worker smoke passed.
Original contract preserved; added working rules merged. No main merge/release,
paid API call or company-source modification is authorized by this follow-up.
New default is detailed; legacy core pilot semantics remain explicit. Production
requires low-confidence review even for legacy comparisons. Schema 7 adds an
audited image-reservation override so existing jobs can resume without rewriting
their frozen settings. Back up before opening; older binaries cannot open v7 DBs.
Corporate references remain outside the repository. Items 4–5 and all pending
company decisions remain unresolved; Mock checks do not establish real accuracy.

## Purpose and constraints
Repository: https://github.com/kosmos-s/llm-change-tool-v2
Two aerial images T1/T2 + original JSON → LLM classification → comparison → human review → separate corrected JSON.
Python 3.11, PySide6, SQLite, SQLAlchemy, Pydantic, PyInstaller. Local-first; no NAS/server requirement.
School pays API costs. Program demonstration and results presentation are the agreed handoff approach; company deployment/integration is not established.
v1 kosmos-s/llm-change-auto is reference only; do not revert to Streamlit/CSV.

## Last verified release
v0.1.10, PR #10 merged, merge SHA 0b63f14b589c200196ebf4ca7522056a634e71ce.
Windows release build succeeded; portable ZIP published:
https://github.com/kosmos-s/llm-change-tool-v2/releases/tag/v0.1.10
Previous tests: 131 pytest passed, Ruff passed, self-test passed, offscreen GUI smoke passed.
12 real-format samples passed import/Mock/review/save/reopen/export/backup/restore and original-file integrity checks.
These do not establish actual paid-API accuracy or human-reviewed dataset quality.

## Next implementation scope
First reproduce against current code; skip already-fixed findings.
1. arti_other_detail can remain after arti_other is cleared. Fix effective review/export data without changing original JSON.
2. core low-confidence behavior: all-zero labels, confidence=0.1, review_required=false matching original labels could become AUTO_KEEP. Review policy intentionally differed from detailed policy. Design explicit review behavior and verify required-review counts, existing jobs and Gate compatibility.
3. Fixed 20,000 input-token reservation can underestimate larger-image requests. Account for model/image dimensions/detail, prompt/schema, output allowance, retries and concurrent reservations. Unknown prices must not silently be zero. Distinguish estimates from a provider-enforced billing cap. Test offline.
4. English reasons are not automatically translated; stale English can be cleared after edits. English deliverable requirement remains undecided. Report options; do not add paid translation automatically.
5. Company model training and area annotation/IoU evaluation are not a complete included pipeline. Do not claim label comparison metrics prove retrained-model gains.

For the next coding task: reproduce and fix items 1–3, add regression tests, run relevant/full required checks, verify affected end-to-end flow with Mock. Commit on a separate branch and open a PR if authorized by the starting prompt. No main merge/release or paid API call in this task.

## Pending company decisions (no answer as of last conversation)
Official F1 vs F2 metric, positive class, evaluation data/performer;
3,000-sample selection scope and split; meaning of FN/FP and filename suffixes;
final development/delivery scope and timeline.
Historical document mismatch: proposal F1 0.80→0.85; company PDF F2 0.80→0.85 and other F1 references. Verify source pages when files available.
Do not start paid 3,000-sample production processing or declare final metric success before criteria are settled.

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
Only after company decisions: select 3,000, run, review, record counts/time/API costs and representative corrections.

