#!/usr/bin/env python3
"""Return the next unresolved line group for a source file.

Usage:
  group-by-line.py <source_file> [--skip-line N ...]

Always returns the full briefing for the LOWEST-numbered line that still has
actionable mutants (survived or no tests) and is not in --skip-line. Calling
this script repeatedly without resolving anything returns the same group — the
only way to advance is to kill the mutants (via verify-mutant.py, which updates
the meta) or mark the line skipped (via --skip-line).

When the user chooses to skip a line (equivalent mutant etc.), pass it as
--skip-line so the next call advances:

  group-by-line.py src/backend_api/mdns.py --skip-line 42

Multiple --skip-line flags are accepted for lines skipped in prior iterations.

Outputs JSON to stdout:

  When a group remains:
  {
    "source_file": "src/backend_api/mdns.py",
    "line": 42,
    "remaining_lines": [42, 67],   # all still-unresolved lines (incl. this one)
    "tests_for_line": ["tests/unit/foo.py::test_x", ...],
    "mutants": [
      {"key": "...__mutmut_1", "status": "survived", "diff": "..."},
      ...
    ]
  }

  When all groups are resolved:
  {
    "source_file": "src/backend_api/mdns.py",
    "done": true
  }

Reads cached mutants/*.meta — run run-mutmut.py first. Calls mutmut show and
mutmut tests-for-mutant only for mutants on the returned line.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from utils import ACTIONABLE_STATUSES
from utils import emit
from utils import find_backend_root
from utils import iter_mutant_records
from utils import run_mutmut

HUNK_RE = re.compile(r"^@@ -(\d+)", re.MULTILINE)


def parse_args() -> tuple[str, set[int]]:
    argv = sys.argv[1:]
    if not argv:
        _ = sys.stderr.write("Usage: group-by-line.py <source_file> [--skip-line N ...]\n")
        sys.exit(2)

    source_file = argv[0]
    skip_lines: set[int] = set()

    i = 1
    while i < len(argv):
        if argv[i] == "--skip-line" and i + 1 < len(argv):
            skip_lines.add(int(argv[i + 1]))
            i += 2
        else:
            _ = sys.stderr.write(f"Unknown argument: {argv[i]!r}\n")
            sys.exit(2)

    return source_file, skip_lines


def get_line_from_diff(diff: str) -> int:
    hunk_match = HUNK_RE.search(diff)
    return int(hunk_match.group(1)) if hunk_match else 0


def main() -> None:
    target, skip_lines = parse_args()
    backend_root = find_backend_root()

    records = [
        r
        for r in iter_mutant_records(backend_root)
        if r["source_file"] == target and r["status"] in ACTIONABLE_STATUSES
    ]

    if not records:
        emit({"source_file": target, "done": True})
        return

    # First pass: get line number for every record (requires mutmut show).
    keyed: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        show = run_mutmut(["show", record["key"]], backend_root, timeout=120)
        if show.returncode != 0:
            _ = sys.stderr.write(f"`mutmut show {record['key']}` failed:\n{show.stderr}\n")
            sys.exit(1)
        line = get_line_from_diff(show.stdout)
        keyed.append((line, {"record": record, "diff": show.stdout.rstrip("\n")}))

    all_lines = sorted({line for line, _ in keyed if line not in skip_lines})

    if not all_lines:
        emit({"source_file": target, "done": True})
        return

    target_line = all_lines[0]

    by_line: dict[int, dict[str, object]] = defaultdict(lambda: {"mutants": [], "tests_for_line": set()})

    for line, data in keyed:
        if line != target_line:
            continue
        record = data["record"]
        diff = data["diff"]
        key = record["key"]

        tests_result = run_mutmut(["tests-for-mutant", key], backend_root, timeout=120)
        tests = [t.strip() for t in tests_result.stdout.splitlines() if "::" in t]

        group = by_line[target_line]
        group["mutants"].append({"key": key, "status": record["status"], "diff": diff})  # type: ignore[union-attr]
        group["tests_for_line"].update(tests)  # type: ignore[union-attr]

    emit(
        {
            "source_file": target,
            "line": target_line,
            "remaining_lines": all_lines,
            "tests_for_line": sorted(by_line[target_line]["tests_for_line"]),  # type: ignore[arg-type]
            "mutants": by_line[target_line]["mutants"],
        }
    )


if __name__ == "__main__":
    main()
