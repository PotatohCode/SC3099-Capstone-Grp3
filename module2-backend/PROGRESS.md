# Backend Test Progress

Ongoing log of `tests/public/` results against the phases in
[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md), so we can see progression
(or regression) checkpoint over checkpoint instead of only trusting memory.

## How to update this file

1. Make sure the stack is up and migrations are applied:
   ```bash
   docker compose up -d postgres redis backend
   ```
2. From the repo root, run the snapshot script and copy its output into a
   new entry under **History** below (newest first):
   ```bash
   ./module2-backend/.venv/Scripts/python module2-backend/scripts/snapshot_tests.py --phase "Phase N"
   ```
3. Add one line to the **Checkpoint summary** table.
4. Write 1-3 sentences under the new entry on what changed since the last
   checkpoint — call out both improvements *and* regressions explicitly. A
   file that went from 5 errors to 3 failed is progress even though "failed"
   sounds worse than "error" (see note below); a file that went from 2
   passed to 0 passed is a regression worth a sentence even if the overall
   pass count went up elsewhere.

**Why per-file counts, not the `tests/scoring/plugin.py` percentage:** that
plugin only scores a test once it reaches the `call` phase, so every test
whose *fixture* setup fails (e.g. `test_student` failing because
`/auth/register` doesn't exist yet) is silently dropped from its
denominator rather than counted against it. Early on, when most tests error
out at fixture setup, that makes its percentage look artificially high. Raw
pytest counts against the full, fixed test collection don't have that
problem, so that's what this file tracks.

**Reading failed vs. errored:** a **failed** test ran and got a wrong
result — worth looking at directly. An **errored** test means a fixture
dependency (usually `/auth/register` or `/auth/login` early on) isn't
implemented yet, so the test body never even ran — expected to clear out
in bulk as each phase lands, not something to chase test-by-test.

Raw JSON snapshots (via `pytest --score-report=...`) are saved alongside
this file in `test-results/` for anyone who wants to diff the raw data
directly instead of reading the markdown tables.

---

## Checkpoint summary

| Date | Phase | Commit | Passed | Failed | Errors | Skipped | Collected |
|---|---|---|---|---|---|---|---|
| 2026-08-23 | Phase 1 (skeleton) | `4f01a24` | 2 | 12 | 67 | 16 | 97 |

---

## History

### 2026-08-23 — Phase 1: skeleton, DB models, Alembic baseline (`4f01a24`)

Baseline checkpoint — no routers exist beyond `/health` yet, so this is the
expected floor, not a regression to chase. 16 skipped are almost entirely
`test_face_recognition.py` (Module 3's service isn't running) plus one
flaky-by-design performance test. All 67 errors are fixture setup calling
`pytest.fail()` when `/auth/register` returns 404 instead of 201 — expect
most of these to clear once phase 2 (auth) lands.

### Snapshot - Phase 1

Overall: **2 passed**, 12 failed, 67 errors, 16 skipped (of 97 collected)

| Test file | Passed | Failed | Errors | Skipped |
|---|---|---|---|---|
| `test_api_functional.py` | 0 | 2 | 14 | 0 |
| `test_face_recognition.py` | 0 | 0 | 0 | 15 |
| `test_frontend_dashboard.py` | 1 | 3 | 11 | 0 |
| `test_integration.py` | 0 | 1 | 2 | 0 |
| `test_observability.py` | 0 | 0 | 20 | 0 |
| `test_performance.py` | 1 | 2 | 4 | 1 |
| `test_privacy_basic.py` | 0 | 0 | 8 | 0 |
| `test_security_basic.py` | 0 | 4 | 8 | 0 |
| **Total** | **2** | **12** | **67** | **16** |
