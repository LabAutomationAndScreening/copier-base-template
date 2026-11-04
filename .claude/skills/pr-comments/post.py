#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Post a reply to a PR comment, for the pr-comments skill.

Usage:
  # Reply in an inline review thread (pulls/comments):
  post.py --pr <number> --comment-id <id> --comment-type pulls/comments --body-file <path> [--repo OWNER/NAME]

  # Answer a top-level PR comment (issues/comments): GitHub has no threads for those, so this posts a new top-level
  # comment, marked so that read.py knows which comment it answers:
  post.py --pr <number> --comment-id <id> --comment-type issues/comments --body-file <path> [--repo OWNER/NAME]

  # Answer a review's own body (pulls/reviews, --comment-id being the review's id): a new top-level comment, marked
  # the same way:
  post.py --pr <number> --comment-id <review id> --comment-type pulls/reviews --body-file <path> [--repo OWNER/NAME]

Either form takes --commit <full sha>, which fills each [COMMIT LINK] in the body file with a markdown link to that
commit as it appears in the PR, the form GitHub associates with the PR. A commit that isn't one of the PR's pushed
commits is refused. A [COMMIT LINK] inside a code span or a fenced code block is text about the placeholder, not a
placeholder, and stays as written.

Without --repo, the PR belongs to the current directory's origin remote. In place of --repo, --checkout PATH posts as
if run from that checkout of another repo, whose origin remote the PR belongs to. gh prefers the login
`gh auth login` stored, which reaches every repo the user can, over a codespace's repo-scoped GITHUB_TOKEN; with no
stored login it uses the environment's GH_TOKEN or GITHUB_TOKEN.

The AI attribution footer is appended to the body file first if it isn't already its last line, so drafts never
include it themselves. On success the comment's URL is printed, then the body exactly as it was posted (links filled,
footer included), so the result can be checked without reading the thread back; the body file is deleted, so a retry
cannot post twice. With --check, it prints where the reply would go and the body as it would be posted, and neither
changes the file nor posts.

Run this only on a reply whose text the user has approved: it posts under their account, and nothing asks them again
before it does. The pr-comments skill has the user approve the draft first; the file then goes out as approved, with
--commit filling [COMMIT LINK] as the only change.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import COMMIT_LINK_PLACEHOLDER
from utils import GH_TIMEOUT_SECONDS
from utils import add_repo_arguments
from utils import count_commit_link_placeholders
from utils import enter_checkout
from utils import fill_commit_link_placeholders
from utils import gh_rest
from utils import gh_run
from utils import issue_comment_reply_marker
from utils import owner_and_repo
from utils import pr_commit_link
from utils import review_reply_marker
from utils import split_code

REPLY_FOOTER = "*Reply drafted by AI (Claude), reviewed and approved by the author before posting.*"
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")


def _in_prose(text: str, *, content: str) -> bool:
    for piece, is_code in split_code(content):
        if is_code:
            continue
        if text in piece:
            return True
    return False


def _pr_commit_shas(*, owner: str, repo: str, pr: int) -> set[str]:
    try:
        commits = gh_rest("api", f"repos/{owner}/{repo}/pulls/{pr}/commits", "--paginate")
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"Cannot list PR #{pr}'s commits: {e.stderr}\n")
        sys.exit(1)
    return {commit["sha"] for commit in commits}


def _commit_link(commit: str | None, *, owner: str, repo: str, pr: int) -> str | None:
    if commit is None:
        return None
    if _FULL_SHA_RE.fullmatch(commit) is None:
        _ = sys.stderr.write(f"--commit must be a full 40-character SHA, not {commit}\n")
        sys.exit(1)
    if commit not in _pr_commit_shas(owner=owner, repo=repo, pr=pr):
        _ = sys.stderr.write(f"--commit {commit} is not one of PR #{pr}'s commits: push it first, or check the SHA.\n")
        sys.exit(1)
    return pr_commit_link(owner=owner, repo=repo, pr=pr, commit=commit)


def _with_commit_link(content: str, *, body_file: Path, link: str | None) -> str:
    """Return the body with each [COMMIT LINK] placeholder replaced by the commit's link in the PR.

    A [COMMIT LINK] inside a code span or a fenced code block is text about the placeholder, not a placeholder: it is
    neither filled nor counted. A body that still carries a placeholder with no commit given, or a commit with no
    placeholder to fill, is refused, so a reply never goes out with a placeholder or without the link it was written
    for. A body with no placeholder left whose prose already holds this commit's link passes, so a failed post can be
    retried with the same arguments.
    """
    placeholders = count_commit_link_placeholders(content)
    if link is None:
        if placeholders:
            _ = sys.stderr.write(f"{body_file} still has {COMMIT_LINK_PLACEHOLDER}; pass --commit <sha> to fill it.\n")
            sys.exit(1)
        return content
    if placeholders == 0:
        if _in_prose(link, content=content):
            return content
        _ = sys.stderr.write(
            f"--commit given, but {body_file} has no {COMMIT_LINK_PLACEHOLDER} to fill (one inside a code span or a"
            " fenced block is text, not a placeholder).\n"
        )
        sys.exit(1)
    return fill_commit_link_placeholders(content, link=link)


def _read_body_file(body_file: Path) -> str:
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"Unable to read body file {body_file}: {e}\n")
        sys.exit(1)


def _with_reply_footer(content: str) -> str:
    """Return the body with the AI attribution footer as its last line, adding it only if it isn't there already."""
    non_empty_lines = [line.strip() for line in content.splitlines() if line.strip()]
    if non_empty_lines and non_empty_lines[-1] == REPLY_FOOTER:
        return content
    # a blank line between the reply and the footer
    suffix = "\n" if content.endswith("\n") else "\n\n"
    return content + suffix + REPLY_FOOTER + "\n"


def _write_body_file(body_file: Path, content: str) -> None:
    try:
        _ = body_file.write_text(content, encoding="utf-8")
    except OSError as e:
        _ = sys.stderr.write(f"Unable to write body file {body_file}: {e}\n")
        sys.exit(1)


def _post(*, endpoint: str, body: str, body_file: Path) -> None:
    """POST the reply with gh api, print its URL and the body as posted, then delete the body file it came from.

    body is the body file's content plus the reply marker, which is never written to the file, so a failed post can be
    retried without markers piling up. The body is printed after the URL because the file is gone once
    the post succeeds, and what went out (the filled links, the footer) is what the user approved only if the fill
    behaved; printing it makes that visible without a read of the thread.

    Exits with status 1 if gh api fails or times out; a timed-out POST may still have reached GitHub, so its message
    says to check before retrying. Once gh api succeeds the comment exists, so an unparsable response still counts as
    posted and the body file is still deleted (otherwise a retry would post a duplicate). A failure to delete the body
    file only warns.
    """
    try:
        result = gh_run(
            ["gh", "api", endpoint, "--method", "POST", "--raw-field", f"body={body}"], timeout=GH_TIMEOUT_SECONDS
        )
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"gh api error: {e.stderr}\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(
            "gh api timed out while posting the reply, but GitHub may have accepted it anyway: check the thread before"
            f" retrying, or the reply may be posted twice. The body file {body_file} was kept.\n"
        )
        sys.exit(1)

    try:
        url = json.loads(result.stdout).get("html_url", "(no URL in response)")
    except json.JSONDecodeError:
        url = "(unparsable response)"
    _ = sys.stdout.write(f"Posted: {url}\nBody as posted:\n{body}")
    if not body.endswith("\n"):
        _ = sys.stdout.write("\n")

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
        choices=["pulls/comments", "issues/comments", "pulls/reviews"],
    )
    _ = parser.add_argument("--body-file", required=True, type=Path)
    _ = parser.add_argument("--pr", type=int, required=True, help="PR number")
    add_repo_arguments(parser)
    _ = parser.add_argument(
        "--commit", default=None, metavar="SHA", help="fills each [COMMIT LINK] in the body with this commit's link"
    )
    _ = parser.add_argument(
        "--check", action="store_true", help="print the body as it would be posted; change and post nothing"
    )
    args = parser.parse_args()
    body_file = args.body_file.resolve()
    enter_checkout(args.checkout)

    owner, repo = owner_and_repo(repo=args.repo)
    link = _commit_link(args.commit, owner=owner, repo=repo, pr=args.pr)
    content = _with_reply_footer(_with_commit_link(_read_body_file(body_file), body_file=body_file, link=link))

    if args.comment_type == "pulls/comments":
        # Reply directly into the inline review comment thread.
        endpoint = f"repos/{owner}/{repo}/pulls/{args.pr}/comments/{args.comment_id}/replies"
        body_suffix = ""
    elif args.comment_type == "pulls/reviews":
        # A review's own body has no thread either, so the answer is a new top-level comment, marked likewise.
        endpoint = f"repos/{owner}/{repo}/issues/{args.pr}/comments"
        body_suffix = f"\n{review_reply_marker(args.comment_id)}\n"
    else:
        # GitHub has no "reply" concept for issue comments — post a new top-level comment, marked so that
        # read.py knows which comment it answers.
        endpoint = f"repos/{owner}/{repo}/issues/{args.pr}/comments"
        body_suffix = f"\n{issue_comment_reply_marker(args.comment_id)}\n"

    if args.check:
        _ = sys.stdout.write(f"Would post to {endpoint}:\n{content}{body_suffix}")
        return
    # the file keeps the filled link and the footer, so a failed post can be retried with the same arguments
    _write_body_file(body_file, content)
    _post(endpoint=endpoint, body=content + body_suffix, body_file=body_file)


if __name__ == "__main__":
    main()
