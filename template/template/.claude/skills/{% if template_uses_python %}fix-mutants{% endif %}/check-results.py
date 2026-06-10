#!/usr/bin/env python3
"""Check whether mutmut has any existing results.

Usage:
  check-results.py

Runs `mutmut results` and checks whether it produced any output. Empty stdout
means mutmut has never been run (or the mutants/ directory was wiped).

Outputs JSON to stdout:
  {
    "has_results": true | false
  }
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import emit
from utils import find_backend_root
from utils import run_mutmut


def main() -> None:
    backend_root = find_backend_root()
    result = run_mutmut(["results"], backend_root, timeout=30)
    has_results = bool(result.stdout.strip())
    emit({"has_results": has_results})


if __name__ == "__main__":
    main()
