#!/usr/bin/env python3
"""Agent-facing tool for the comment-audit skill. Two verbs, sharing the gate's detection via utils.py.

Usage:
  comment-audit.py list  <repo-root>   Print the audited comments as JSON:
                                         {base, head, gitDir, comments: [{file, start, end, raws, kind,
                                         block}]}. Same detection and range as the gate, so what the skill
                                         reviews is exactly what the gate would block.

  comment-audit.py stamp <repo-root>   Record HEAD in <git-dir>/.comment-audit-ok so the gate lets the
                                         next push through. Run AFTER the final commit — the marker must
                                         match HEAD, and the gate consumes it (single-use) on that push.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import collect_for_review
from utils import stamp_approval

EXPECTED_ARG_COUNT = 3


def main() -> None:
    if len(sys.argv) != EXPECTED_ARG_COUNT or sys.argv[1] not in ("list", "stamp"):
        _ = sys.stderr.write(f"Usage: {sys.argv[0]} {{list|stamp}} <repo-root>\n")
        sys.exit(1)

    verb = sys.argv[1]
    cwd = sys.argv[2]

    if verb == "list":
        _ = sys.stdout.write(json.dumps(collect_for_review(cwd), indent=2) + "\n")
        return

    head, marker = stamp_approval(cwd)
    _ = sys.stdout.write(f"comment-audit: stamped {head} at {marker}\n")


if __name__ == "__main__":
    main()
