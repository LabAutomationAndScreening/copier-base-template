#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Replace the [COMMIT LINK] placeholder in a reply file with the PR-scoped commit link.

Usage: commit_link.py <reply-file> [--pr <number>] [--commit <hash>] [--checkout <path>]

Everything is self-derived when the optional flags are omitted:
  --pr     auto-detected from the current branch via `gh pr view`
  --commit defaults to HEAD

The link points at the commit *within the PR* (/pull/<pr>/commits/<hash>)
rather than the repo-wide commit view (/commit/<hash>), so replies posted
against it are associated with the PR. Owner and repo are derived from the git remote
automatically.

Prints "replaced" on success. Exits non-zero if the placeholder is absent.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from utils import COMMIT_LINK_PLACEHOLDER
from utils import count_commit_link_placeholders
from utils import enter_checkout
from utils import fill_commit_link_placeholders
from utils import owner_repo_from_remote
from utils import pr_commit_link
from utils import run_cmd


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
    _ = parser.add_argument("--checkout", type=Path, default=None, help="a checkout of the PR's repo, if not this one")
    args = parser.parse_args()
    reply_file = args.reply_file.resolve()
    enter_checkout(args.checkout)

    try:
        content = reply_file.read_text(encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"File error for {reply_file}: {e}\n")
        sys.exit(1)

    if count_commit_link_placeholders(content) == 0:
        _ = sys.stderr.write(
            f"Placeholder {COMMIT_LINK_PLACEHOLDER} not found in {reply_file} (one inside a code span or a fenced"
            " block is text, not a placeholder).\n"
        )
        sys.exit(1)

    owner, repo = owner_repo_from_remote()
    pr = args.pr if args.pr is not None else detect_pr()
    link = pr_commit_link(owner=owner, repo=repo, pr=pr, commit=resolve_commit(args.commit))

    try:
        _ = reply_file.write_text(fill_commit_link_placeholders(content, link=link), encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"File error for {reply_file}: {e}\n")
        sys.exit(1)
    _ = sys.stdout.write("replaced\n")


if __name__ == "__main__":
    main()
