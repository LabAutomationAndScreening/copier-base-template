#!/usr/bin/env python3
"""Post a reply to a PR comment, for the pr-comments skill.

Usage:
  # Reply in an inline review thread (pulls/comments):
  post.py --pr <number> --comment-id <id> --comment-type pulls/comments --body-file <path> [--repo OWNER/NAME]

  # Answer a top-level PR comment (issues/comments): GitHub has no threads for those, so this posts a new top-level
  # comment, marked so that read.py knows which comment it answers:
  post.py --pr <number> --comment-id <id> --comment-type issues/comments --body-file <path> [--repo OWNER/NAME]

Without --repo, the PR belongs to the current directory's origin remote. gh prefers the login `gh auth login` stored,
which reaches every repo the user can, over a codespace's repo-scoped GITHUB_TOKEN; with no stored login it uses the
environment's GH_TOKEN or GITHUB_TOKEN.

The AI attribution footer is appended to the body file first if it isn't already its last line, so drafts never
include it themselves. On success the body file is deleted, so a retry cannot post twice.

Posting goes out under the user's account, so the permission settings put this script under ask: show the user the
reply, then run it, and the prompt is their approval.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GH_TIMEOUT_SECONDS
from utils import gh_run
from utils import issue_comment_reply_marker
from utils import owner_and_repo

REPLY_FOOTER = "*Reply drafted by AI (Claude), reviewed and approved by the author before posting.*"


def _read_body_file(body_file: Path) -> str:
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"Unable to read body file {body_file}: {e}\n")
        sys.exit(1)


def _ensure_reply_footer(body_file: Path) -> None:
    """Make the AI attribution footer the last line of the reply file.

    Adding it is idempotent, so a reply file can go through this any number of times. Exits with status 1 if the file
    can't be read or written.
    """
    content = _read_body_file(body_file)
    non_empty_lines = [line.strip() for line in content.splitlines() if line.strip()]
    if non_empty_lines and non_empty_lines[-1] == REPLY_FOOTER:
        return
    # a blank line between the reply and the footer
    suffix = "\n" if content.endswith("\n") else "\n\n"
    try:
        _ = body_file.write_text(content + suffix + REPLY_FOOTER + "\n", encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"Unable to write body file {body_file}: {e}\n")
        sys.exit(1)


def _post(*, endpoint: str, body_file: Path, body_suffix: str) -> None:
    """POST the reply to a GitHub API endpoint with gh api, print its URL, then delete the body file it came from.

    The comment's `body` is read from body_file, with body_suffix appended (the file itself is not changed, so a failed
    post can be retried without the suffix piling up).

    Exits with status 1 if gh api fails. Once gh api succeeds the comment exists, so an unparsable response still counts
    as posted and the body file is still deleted (otherwise a retry would post a duplicate). A failure to delete the body
    file only warns.
    """
    body = _read_body_file(body_file) + body_suffix
    try:
        result = gh_run(
            ["gh", "api", endpoint, "--method", "POST", "--raw-field", f"body={body}"], timeout=GH_TIMEOUT_SECONDS
        )
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"gh api error: {e.stderr}\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write("gh api timed out while posting the reply.\n")
        sys.exit(1)

    try:
        url = json.loads(result.stdout).get("html_url", "(no URL in response)")
    except json.JSONDecodeError:
        url = "(unparsable response)"
    _ = sys.stdout.write(f"Posted: {url}\n")

    try:
        body_file.unlink()
    except OSError as e:
        _ = sys.stderr.write(f"Warning: post succeeded but could not delete body file {body_file}: {e}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--comment-id", required=True, type=int)
    _ = parser.add_argument(
        "--comment-type",
        required=True,
        choices=["pulls/comments", "issues/comments"],
    )
    _ = parser.add_argument("--body-file", required=True, type=Path)
    _ = parser.add_argument("--pr", type=int, required=True, help="PR number")
    _ = parser.add_argument(
        "--repo", default=None, metavar="OWNER/NAME", help="the PR's repo (default: the origin remote's)"
    )
    args = parser.parse_args()

    owner, repo = owner_and_repo(repo=args.repo)

    if args.comment_type == "pulls/comments":
        # Reply directly into the inline review comment thread.
        endpoint = f"repos/{owner}/{repo}/pulls/{args.pr}/comments/{args.comment_id}/replies"
        body_suffix = ""
    else:
        # GitHub has no "reply" concept for issue comments — post a new top-level comment, marked so that
        # read.py knows which comment it answers.
        endpoint = f"repos/{owner}/{repo}/issues/{args.pr}/comments"
        body_suffix = f"\n{issue_comment_reply_marker(args.comment_id)}\n"

    _ensure_reply_footer(args.body_file)
    _post(endpoint=endpoint, body_file=args.body_file, body_suffix=body_suffix)


if __name__ == "__main__":
    main()
