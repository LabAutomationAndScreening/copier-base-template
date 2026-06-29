#!/usr/bin/env python3
"""Replace the [COMMIT LINK] placeholder in a reply file with the PR-scoped commit link.

Usage: commit-link.py <reply-file> [--pr <number>] [--commit <hash>]

Everything is self-derived when the optional flags are omitted:
  --pr     auto-detected from the current branch via `gh pr view`
  --commit defaults to HEAD

The link points at the commit *within the PR* (/pull/<pr>/commits/<hash>)
rather than the repo-wide commit view (/commit/<hash>), so replies posted
against it are associated with the PR. Owner and repo are derived from the
git remote automatically.

Prints "replaced" on success. Exits non-zero if the placeholder is absent.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import owner_repo_from_remote
from utils import run_cmd

PLACEHOLDER = "[COMMIT LINK]"


def resolve_commit(ref: str) -> str:
    try:
        result = run_cmd(
            ["git", "rev-parse", ref],
            timeout=15,
            timeout_msg=f"Timed out resolving commit ref '{ref}'.",
        )
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"Cannot resolve commit ref '{ref}': {e.stderr}\n")
        sys.exit(1)
    return result.stdout.strip()


def detect_pr() -> int:
    try:
        result = run_cmd(
            ["gh", "pr", "view", "--json", "number"],
            timeout=30,
            timeout_msg="Timed out detecting the PR for the current branch.",
        )
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"Cannot detect a PR for the current branch: {e.stderr}\nPass --pr explicitly.\n")
        sys.exit(1)
    return int(json.loads(result.stdout)["number"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("reply_file", type=Path, help="Reply file containing the [COMMIT LINK] placeholder")
    _ = parser.add_argument("--pr", type=int, default=None, help="PR number (default: auto-detect from current branch)")
    _ = parser.add_argument("--commit", default="HEAD", help="Commit ref to link (default: HEAD)")
    args = parser.parse_args()

    try:
        content = args.reply_file.read_text(encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"File error for {args.reply_file}: {e}\n")
        sys.exit(1)

    if PLACEHOLDER not in content:
        _ = sys.stderr.write(f"Placeholder {PLACEHOLDER} not found in {args.reply_file}.\n")
        sys.exit(1)

    owner, repo = owner_repo_from_remote()
    pr = args.pr if args.pr is not None else detect_pr()
    commit = resolve_commit(args.commit)
    link = f"https://github.com/{owner}/{repo}/pull/{pr}/commits/{commit}"

    try:
        _ = args.reply_file.write_text(content.replace(PLACEHOLDER, link), encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"File error for {args.reply_file}: {e}\n")
        sys.exit(1)
    _ = sys.stdout.write("replaced\n")


if __name__ == "__main__":
    main()
