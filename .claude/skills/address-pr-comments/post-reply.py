#!/usr/bin/env python3
"""Post a reply to a PR comment thread via the GitHub API.

Usage:
  # Reply to an inline review comment thread (pulls/comments):
  post-reply.py --comment-id <id> --comment-type pulls/comments --body-file <path> --pr <number>

  # Post a general PR comment (issues/comments — no threading, posts top-level):
  post-reply.py --comment-id <id> --comment-type issues/comments --body-file <path> --pr <number>

Owner and repo are derived from the git remote automatically.

This script exists so that gh api calls are covered by the skills allow-list
rather than requiring manual approval each time.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import owner_repo_from_remote
from utils import post_via_gh_api
from utils import read_body_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--comment-id", required=True, type=int)
    _ = parser.add_argument(
        "--comment-type",
        required=True,
        choices=["pulls/comments", "issues/comments"],
    )
    _ = parser.add_argument("--body-file", required=True, type=Path)
    _ = parser.add_argument("--pr", type=int, required=True, help="PR number")
    args = parser.parse_args()

    owner, repo = owner_repo_from_remote()
    body = read_body_file(args.body_file)

    if args.comment_type == "pulls/comments":
        # Reply directly into the inline review comment thread.
        endpoint = f"repos/{owner}/{repo}/pulls/{args.pr}/comments/{args.comment_id}/replies"
    else:
        # GitHub has no "reply" concept for issue comments — post a new top-level comment.
        endpoint = f"repos/{owner}/{repo}/issues/{args.pr}/comments"

    post_via_gh_api(
        cmd=["gh", "api", endpoint, "--method", "POST", "--raw-field", f"body={body}"],
        body_file=args.body_file,
        timeout_msg="gh api timed out while posting reply.",
    )


if __name__ == "__main__":
    main()
