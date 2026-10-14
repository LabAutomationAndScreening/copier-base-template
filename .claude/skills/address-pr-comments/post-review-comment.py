#!/usr/bin/env python3
"""Post a new inline review comment on a PR diff via the GitHub API.

Usage:
  # Comment on one line of the new file:
  post-review-comment.py --pr <number> --path <repo-relative path> --line <n> --body-file <path>

  # Comment spanning a range of lines (start and end must be in the same diff hunk):
  post-review-comment.py --pr <number> --path <repo-relative path> --start-line <n> --line <m> --body-file <path>

  # Comment on a removed line (the old file's numbering):
  post-review-comment.py --pr <number> --path <repo-relative path> --line <n> --side LEFT --body-file <path>

Line numbers are those of the file at --commit-id (default: the PR's current head) for --side RIGHT, or of the base
file for --side LEFT. Owner and repo are derived from the git remote automatically.

This script exists so that gh api calls are covered by the skills allow-list
rather than requiring manual approval each time.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import owner_repo_from_remote
from utils import post_via_gh_api
from utils import read_body_file
from utils import run_cmd


def pr_head_sha(*, owner: str, repo: str, pr: int) -> str:
    try:
        result = run_cmd(
            ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr}", "--jq", ".head.sha"],
            timeout=30,
            timeout_msg="gh api timed out while reading the PR head commit.",
        )
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"gh api error reading PR #{pr}: {e.stderr}\n")
        sys.exit(1)
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--pr", type=int, required=True, help="PR number")
    _ = parser.add_argument("--path", required=True, help="File path relative to the repo root")
    _ = parser.add_argument("--line", type=int, required=True, help="Line the comment ends on")
    _ = parser.add_argument("--start-line", type=int, help="First line of a multi-line comment")
    _ = parser.add_argument("--side", choices=["RIGHT", "LEFT"], default="RIGHT", help="RIGHT = new file, LEFT = old")
    _ = parser.add_argument("--start-side", choices=["RIGHT", "LEFT"], help="Defaults to --side")
    _ = parser.add_argument("--commit-id", help="Commit the line numbers refer to (default: the PR's head)")
    _ = parser.add_argument("--body-file", required=True, type=Path)
    args = parser.parse_args()

    if args.start_line is not None and args.start_line >= args.line:
        _ = sys.stderr.write(f"--start-line ({args.start_line}) must be less than --line ({args.line})\n")
        sys.exit(1)

    owner, repo = owner_repo_from_remote()
    body = read_body_file(args.body_file)

    commit_id = args.commit_id
    if commit_id is None:
        commit_id = pr_head_sha(owner=owner, repo=repo, pr=args.pr)

    fields = {
        "body": body,
        "commit_id": commit_id,
        "path": args.path,
        "side": args.side,
    }
    if args.start_line is not None:
        fields["start_side"] = args.side if args.start_side is None else args.start_side
    cmd = ["gh", "api", f"repos/{owner}/{repo}/pulls/{args.pr}/comments", "--method", "POST"]
    for key, value in fields.items():
        cmd += ["--raw-field", f"{key}={value}"]
    cmd += ["--field", f"line={args.line}"]
    if args.start_line is not None:
        cmd += ["--field", f"start_line={args.start_line}"]

    post_via_gh_api(cmd=cmd, body_file=args.body_file, timeout_msg="gh api timed out while posting the review comment.")


if __name__ == "__main__":
    main()
