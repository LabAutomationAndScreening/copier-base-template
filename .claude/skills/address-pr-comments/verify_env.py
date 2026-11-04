#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Gather environment facts for the address-pr-comments skill as one JSON verdict.

Usage: verify_env.py [--pr <number>] [--checkout <path>]

Emits a JSON object to stdout:
  repo_root            absolute path to the repo root
  has_remote           whether any git remote is configured
  branch               current branch name
  on_protected_branch  whether the branch is main or master
  dirty                whether the working tree has uncommitted changes
  pr                   {number, state, title} for the PR, or null if none found

This reports facts only — it does not enforce the skill's STOP / resume policy.
The caller decides what to do (e.g. dirty is fatal normally but expected under
--resume). With --pr, that PR is looked up; otherwise the PR is auto-detected
from the current branch. With --checkout, every fact is about that checkout of
another repo rather than the current directory's.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from utils import enter_checkout
from utils import gh_run


def run(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — cmd is a fixed argv of literals plus a validated PR number
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def repo_root() -> str:
    result = run(["git", "rev-parse", "--show-toplevel"], timeout=15)
    if result.returncode != 0:
        _ = sys.stderr.write(f"Not inside a git repository: {result.stderr.strip()}\n")
        sys.exit(1)
    return result.stdout.strip()


def current_branch() -> str:
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=15)
    if result.returncode != 0:
        _ = sys.stderr.write(f"Cannot determine current branch: {result.stderr.strip()}\n")
        sys.exit(1)
    return result.stdout.strip()


_GITHUB_URL_RE = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)[^/]+/[^/]+?(?:\.git)?/?")


def has_remote() -> bool:
    result = run(["git", "remote"], timeout=15)
    if result.returncode != 0:
        _ = sys.stderr.write(f"Cannot read git remotes: {result.stderr.strip()}\n")
        sys.exit(1)
    if "origin" not in result.stdout.split():
        return False
    url_result = run(["git", "remote", "get-url", "origin"], timeout=15)
    if url_result.returncode != 0:
        return False
    return bool(_GITHUB_URL_RE.fullmatch(url_result.stdout.strip()))


def is_dirty() -> bool:
    result = run(["git", "status", "--porcelain"], timeout=15)
    if result.returncode != 0:
        _ = sys.stderr.write(f"Cannot read git status: {result.stderr.strip()}\n")
        sys.exit(1)
    return bool(result.stdout.strip())


def check_gh_auth() -> None:
    result = run(["gh", "auth", "status"], timeout=15)
    if result.returncode != 0:
        _ = sys.stderr.write("GitHub CLI is not authenticated. Run: gh auth login\n")
        sys.exit(1)


def find_pr(pr_number: int | None) -> dict[str, object] | None:
    check_gh_auth()
    target = [] if pr_number is None else [str(pr_number)]
    try:
        result = gh_run(["gh", "pr", "view", *target, "--json", "number,state,title"], timeout=30)
    except subprocess.CalledProcessError:
        return None
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--pr", type=int, default=None, help="PR number (default: auto-detect from current branch)")
    _ = parser.add_argument("--checkout", type=Path, default=None, help="a checkout of another repo to report on")
    args = parser.parse_args()
    enter_checkout(args.checkout)

    branch = current_branch()
    on_protected_branch = branch in {"main", "master"}

    verdict = {
        "repo_root": repo_root(),
        "has_remote": has_remote(),
        "branch": branch,
        "on_protected_branch": on_protected_branch,
        "dirty": is_dirty(),
        "pr": find_pr(args.pr),
    }
    _ = sys.stdout.write(json.dumps(verdict, indent=2) + "\n")


if __name__ == "__main__":
    main()
