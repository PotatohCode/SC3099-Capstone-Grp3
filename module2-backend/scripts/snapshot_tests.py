#!/usr/bin/env python3
"""
Run tests/public/ and print a markdown snapshot for PROGRESS.md.

Groups results by file rather than using tests/scoring/plugin.py's point
percentage directly - that plugin only scores tests that reach the "call"
phase, so it silently drops every test whose fixture setup failed (which,
early on, is most of them) instead of counting it against the total. That
makes its percentage misleadingly high while fixtures are still failing.
Per-file pass/fail/error/skip counts against the fixed 90-test collection
don't have that problem, so that's the primary number this script reports.

Usage:
    python module2-backend/scripts/snapshot_tests.py [--phase "Phase 2"]

Requires the backend (and postgres/redis) already running, e.g.:
    docker compose up -d postgres redis backend
"""
import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# PASSED/FAILED/ERROR print as "OUTCOME tests/public/file.py::Class::test" (a
# nodeid). SKIPPED prints differently - "SKIPPED [N] tests\public\file.py:LINE:
# reason" (file:line, no nodeid, and a literal backslash path on Windows) -
# so it needs its own pattern.
RESULT_RE = re.compile(r"^(PASSED|FAILED|ERROR) tests/public/(\S+?)(?:::|$)")
SKIP_RE = re.compile(r"^SKIPPED \[\d+\] tests[/\\]public[/\\](\S+?):\d+:")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default="", help="Label for this checkpoint, e.g. 'Phase 2'")
    parser.add_argument(
        "--backend-url", default=os.getenv("TEST_BACKEND_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--face-url", default=os.getenv("TEST_FACE_URL", "http://localhost:8001")
    )
    args = parser.parse_args()

    env = os.environ.copy()
    env["TEST_BACKEND_URL"] = args.backend_url
    env["TEST_FACE_URL"] = args.face_url

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/public/", "-q", "--no-header", "--tb=no", "-rA", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr

    by_file: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for line in output.splitlines():
        line = line.strip()
        m = RESULT_RE.match(line)
        if m:
            outcome, file_name = m.groups()
            by_file[file_name][outcome] += 1
            continue
        m = SKIP_RE.match(line)
        if m:
            by_file[m.group(1)]["SKIPPED"] += 1

    total = defaultdict(int)
    for counts in by_file.values():
        for outcome, n in counts.items():
            total[outcome] += n

    label = f" - {args.phase}" if args.phase else ""
    print(f"### Snapshot{label}\n")
    print(f"Overall: **{total['PASSED']} passed**, {total['FAILED']} failed, "
          f"{total['ERROR']} errors, {total['SKIPPED']} skipped "
          f"(of {sum(total.values())} collected)\n")
    print("| Test file | Passed | Failed | Errors | Skipped |")
    print("|---|---|---|---|---|")
    for file_name in sorted(by_file):
        c = by_file[file_name]
        print(f"| `{file_name}` | {c['PASSED']} | {c['FAILED']} | {c['ERROR']} | {c['SKIPPED']} |")
    print(f"| **Total** | **{total['PASSED']}** | **{total['FAILED']}** | "
          f"**{total['ERROR']}** | **{total['SKIPPED']}** |")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
