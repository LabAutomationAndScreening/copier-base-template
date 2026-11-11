#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Post a reply to a PR comment, or a new top-level comment, for the pr-comments skill.

Usage:
  # A new top-level comment that answers no other comment (asking a reviewer for a review, say):
  post.py --pr <number> --body-file <path> [--repo OWNER/NAME]

  # Reply in an inline review thread (pulls/comments):
  post.py --pr <number> --comment-id <id> --comment-type pulls/comments --body-file <path> [--repo OWNER/NAME]

  # Answer a top-level PR comment (issues/comments): GitHub has no threads for those, so this posts a new top-level
  # comment, marked so that read.py knows which comment it answers:
  post.py --pr <number> --comment-id <id> --comment-type issues/comments --body-file <path> [--repo OWNER/NAME]

  # Answer a review's own body (pulls/reviews, --comment-id being the review's id): a new top-level comment, marked
  # the same way:
  post.py --pr <number> --comment-id <review id> --comment-type pulls/reviews --body-file <path> [--repo OWNER/NAME]

  # Start a new review thread on a line of the PR's diff, or with no --line on the whole file:
  post.py --pr <number> --path <file> [--line <line>] --body-file <path> [--checkout PATH]

--comment-id and --comment-type go together: both to answer a comment, neither for a new comment.

A new thread sits on the PR's head commit, and --line is a line of the file as it is there, on the new side of the
diff. GitHub only takes a line comment inside the PR's diff hunks (the changed lines and the 3 lines of context around
them), so a line outside them, or a path the PR doesn't change, is refused before anything is posted. Checking that
reads the diff from git, so a new thread is started from a checkout of the PR's repo (the current directory, or
--checkout), never with --repo.

Every form takes --commit <full sha>, which fills each [COMMIT LINK] in the body file with a markdown link to that
commit as it appears in the PR, the form GitHub associates with the PR. A commit that isn't one of the PR's pushed
commits is refused, except on a PR with more commits than GitHub lists (250), where it is only warned about. A
[COMMIT LINK] inside a code span or a fenced code block is text about the placeholder, not a placeholder, and stays
as written.

Without --repo, the PR belongs to the current directory's origin remote. In place of --repo, --checkout PATH posts as
if run from that checkout of another repo, whose origin remote the PR belongs to; --body-file still resolves against
the directory this runs in, as every path argument of these scripts does. gh prefers the login `gh auth login` stored,
which reaches every repo the user can, over a codespace's repo-scoped GITHUB_TOKEN; with no stored login it uses the
environment's GH_TOKEN or GITHUB_TOKEN.

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
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import COMMIT_LINK_PLACEHOLDER
from utils import GH_TIMEOUT_SECONDS
from utils import add_repo_arguments
from utils import commentable_lines
from utils import count_commit_link_placeholders
from utils import ensure_commit
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
# GitHub lists at most this many of a PR's commits, through REST and GraphQL alike
PR_COMMITS_LISTED_AT_MOST = 250


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
    pr_commits = _pr_commit_shas(owner=owner, repo=repo, pr=pr)
    if commit not in pr_commits:
        if len(pr_commits) >= PR_COMMITS_LISTED_AT_MOST:
            _ = sys.stderr.write(
                f"Warning: --commit {commit} is not among the {len(pr_commits)} commits GitHub lists for PR #{pr}, "
                "its most it will list, so it can't be checked; linking it anyway.\n"
            )
        else:
            _ = sys.stderr.write(
                f"--commit {commit} is not one of PR #{pr}'s commits: push it first, or check the SHA.\n"
            )
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
    """Return the body with the AI attribution footer as its last line.

    A body that already ends with the footer (a retry of a failed post, say) is returned as it is, so the footer is
    never doubled; otherwise the footer is appended after a blank line.
    """
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


def _post(
    *, endpoint: str, body: str, body_file: Path, fields: dict[str, str] | None = None, line: int | None = None
) -> None:
    """POST the reply with gh api, print its URL and the body as posted, then delete the body file it came from.

    body is the body file's content plus the reply marker, which is never written to the file, so a failed post can be
    retried without markers piling up. fields are the other string fields the endpoint takes (where a new thread sits),
    and line its line number, sent as a number rather than a string. The body is printed after the URL because the file is gone once
    the post succeeds, and what went out (the filled links, the footer) is what the user approved only if the fill
    behaved; printing it makes that visible without a read of the thread.

    Exits with status 1 if gh api fails or times out; a timed-out POST may still have reached GitHub, so its message
    says to check before retrying. Once gh api succeeds the comment exists, so an unparsable response still counts as
    posted and the body file is still deleted (otherwise a retry would post a duplicate). A failure to delete the body
    file only warns.
    """
    args = ["gh", "api", endpoint, "--method", "POST", "--raw-field", f"body={body}"]
    if fields is not None:
        for name, value in fields.items():
            args += ["--raw-field", f"{name}={value}"]
    if line is not None:
        # --field sends a number as a number; GitHub rejects a line given as a string
        args += ["--field", f"line={line}"]
    try:
        result = gh_run(args, timeout=GH_TIMEOUT_SECONDS)
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


def _new_thread_fields(*, owner: str, repo: str, pr: int, path: str, line: int | None) -> dict[str, str]:
    """Return where a new review thread sits: the PR's head commit, the path, and for a file-level one its subject type.

    Exits with status 1, posting nothing, when the PR's commits can't be read, when the PR doesn't change the path, or
    when the line is outside the PR's diff hunks at its head, since GitHub would refuse the comment there.
    """
    try:
        pull_request = gh_rest("api", f"repos/{owner}/{repo}/pulls/{pr}")
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"Cannot read PR #{pr}: {e.stderr}\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(f"Reading PR #{pr} timed out after {GH_TIMEOUT_SECONDS}s; nothing was posted.\n")
        sys.exit(1)
    try:
        head = ensure_commit(pull_request["head"]["sha"])
        base = ensure_commit(pull_request["base"]["sha"])
        commentable = commentable_lines(base=base, anchor=head)
    except RuntimeError as e:
        _ = sys.stderr.write(f"Cannot read PR #{pr}'s diff from this checkout: {e}\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(
            f"Reading PR #{pr}'s diff from this checkout timed out after {GH_TIMEOUT_SECONDS}s; nothing was posted.\n"
        )
        sys.exit(1)
    if path not in commentable:
        _ = sys.stderr.write(
            f"{path} is not part of PR #{pr}'s diff, so no review thread can start on it; post a top-level comment"
            " instead (leave out --path).\n"
        )
        sys.exit(1)
    if line is None:
        return {"commit_id": head, "path": path, "subject_type": "file"}
    if line not in commentable[path]:
        _ = sys.stderr.write(
            f"{path}:{line} at PR #{pr}'s head {head[:7]} is outside the PR's diff hunks, so GitHub won't take a comment"
            " there; pick a line within 3 lines of a change, or leave out --line to comment on the whole file.\n"
        )
        sys.exit(1)
    return {"commit_id": head, "path": path, "side": "RIGHT"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--comment-id", default=None, type=int, help="the comment this answers")
    _ = parser.add_argument(
        "--comment-type",
        default=None,
        choices=["pulls/comments", "issues/comments", "pulls/reviews"],
        help="the answered comment's type",
    )
    _ = parser.add_argument(
        "--path", default=None, help="start a new review thread on this file, one the PR changes, instead of replying"
    )
    _ = parser.add_argument(
        "--line",
        default=None,
        type=int,
        help="with --path: the line, at the PR's head, the new thread sits on; without it the thread is on the file",
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
    if (args.comment_id is None) != (args.comment_type is None):
        parser.error("--comment-id and --comment-type go together: both to answer a comment, neither for a new one")
    if args.line is not None:
        if args.path is None:
            parser.error("--line needs --path: it is a line of the file the new thread starts on")
    if args.path is not None:
        if args.comment_id is not None:
            parser.error("--path starts a new thread, so it can't also answer --comment-id")
        if args.repo is not None:
            parser.error(
                "--path checks the line against the PR's diff in git, so run it from a checkout (or --checkout)"
            )
    return args


@dataclass(frozen=True)
class _Destination:
    endpoint: str
    # a marker after the body, saying which comment a new top-level comment answers
    body_suffix: str
    # where a new review thread sits, for a comment that starts one
    thread_fields: dict[str, str] | None


def _destination(*, args: argparse.Namespace, owner: str, repo: str) -> _Destination:
    if args.path is not None:
        return _Destination(
            endpoint=f"repos/{owner}/{repo}/pulls/{args.pr}/comments",
            body_suffix="",
            thread_fields=_new_thread_fields(owner=owner, repo=repo, pr=args.pr, path=args.path, line=args.line),
        )
    if args.comment_type is None:
        return _Destination(
            endpoint=f"repos/{owner}/{repo}/issues/{args.pr}/comments", body_suffix="", thread_fields=None
        )
    if args.comment_type == "pulls/comments":
        # Reply directly into the inline review comment thread.
        return _Destination(
            endpoint=f"repos/{owner}/{repo}/pulls/{args.pr}/comments/{args.comment_id}/replies",
            body_suffix="",
            thread_fields=None,
        )
    if args.comment_type == "pulls/reviews":
        # A review's own body has no thread either, so the answer is a new top-level comment, marked likewise.
        return _Destination(
            endpoint=f"repos/{owner}/{repo}/issues/{args.pr}/comments",
            body_suffix=f"\n{review_reply_marker(args.comment_id)}\n",
            thread_fields=None,
        )
    # GitHub has no "reply" concept for issue comments — post a new top-level comment, marked so that
    # read.py knows which comment it answers.
    return _Destination(
        endpoint=f"repos/{owner}/{repo}/issues/{args.pr}/comments",
        body_suffix=f"\n{issue_comment_reply_marker(args.comment_id)}\n",
        thread_fields=None,
    )


def main() -> None:
    args = _parse_args()
    body_file = args.body_file.resolve()
    enter_checkout(args.checkout)

    owner, repo = owner_and_repo(repo=args.repo)
    link = _commit_link(args.commit, owner=owner, repo=repo, pr=args.pr)
    content = _with_reply_footer(_with_commit_link(_read_body_file(body_file), body_file=body_file, link=link))
    destination = _destination(args=args, owner=owner, repo=repo)

    if args.check:
        where = destination.endpoint
        if destination.thread_fields is not None:
            location = args.path if args.line is None else f"{args.path}:{args.line}"
            where = f"{where}, as a new thread on {location} at {destination.thread_fields['commit_id'][:7]}"
        _ = sys.stdout.write(f"Would post to {where}:\n{content}{destination.body_suffix}")
        return
    # the file keeps the filled link and the footer, so a failed post can be retried with the same arguments
    _write_body_file(body_file, content)
    _post(
        endpoint=destination.endpoint,
        body=content + destination.body_suffix,
        body_file=body_file,
        fields=destination.thread_fields,
        line=args.line,
    )


if __name__ == "__main__":
    main()
