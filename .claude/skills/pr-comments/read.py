#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Read a PR's comments, grouped into threads, for the pr-comments skill.

Usage:
  read.py <pr_number> [--repo OWNER/NAME]                        actionable threads (the default)
  read.py <pr_number> --needs-verification [--repo OWNER/NAME]   AI review findings with a reply awaiting a verdict
  read.py <pr_number> --thread <comment id> [--repo OWNER/NAME]  one thread or top-level comment, whatever its state
  read.py <pr_number> --all [--repo OWNER/NAME]                  resolved and addressed threads and comments too

Without --repo, the PR belongs to the current directory's origin remote. In place of --repo, --checkout PATH reads as
if run from that checkout of another repo: the PR belongs to its origin remote, and `current_line` is worked out at its
HEAD. gh prefers the login `gh auth login` stored, which reaches every repo the user can, over a codespace's
repo-scoped GITHUB_TOKEN; with no stored login it uses the environment's GH_TOKEN or GITHUB_TOKEN.

Outputs JSON array of comment threads to stdout. Each entry:
  {
    "id": <root comment id>,
    "type": "pulls/comments" | "issues/comments" | "pulls/reviews",
    "url": "<html url of the root comment>",
    "author": "<login>",
    "author_is_bot": <bool>,
    "body": "<text>",
    "body_text": "<body with the reviewer's AI-agent prompt block, HTML comments and HTML tags removed; code untouched>",
    "created_at": "<iso8601>",
    "path": "<file path, pulls/comments only>",
    "line": <line number, pulls/comments with subject_type "line" only>,
    "subject_type": "line" | "file" | null,
    "outdated": <true when the commented line changed after the comment was made>,
    "original_line": <line number in original_commit_id, pulls/comments only>,
    "original_commit_id": "<sha the comment was made on, or the review's commit; null for issues/comments>",
    "current_line": <where original_line is at the current directory's HEAD; null if that line changed, or for a
                     file-level comment, or when original_commit_id is not in the current directory's repo>,
    "line_changed": <true if original_line has been changed or deleted since original_commit_id; null if unknown>,
    "resolved": <bool; always false for issues/comments and pulls/reviews, which GitHub cannot resolve>,
    "open": <bool; whether it is actionable, i.e. in the default output>,
    "ai_review": null | {
      "finding_id": "<e.g. F8>",
      "related": [{"finding_id", "comment_id", "open"}, ...],
      "status": "open" | "awaiting_verification" | "accepted" | "disputed",
      "verdict_rounds": <number of verdicts posted so far>
    },
    "replies": [{"id", "url", "author", "author_is_bot", "body", "body_text", "created_at", "ai_review_verdict"}, ...]
  }

When a comment is outdated, `line` falls back to `original_line`, which is a line number in original_commit_id, not in
the current code.

`ai_review` is set on findings from an AI code review. They carry the current user as author (they are posted under
the account of whoever ran the review), so they are kept despite the filters below until the user replies. In
`related`, comment_id is null when the related finding is not on this PR, and open says whether it is still in the
default output. `status` says who the thread is waiting on:
  - open: no reply from the current user yet, or someone else has the last word
  - awaiting_verification: the current user replied and no verdict has judged that reply yet
  - accepted / disputed: the last reply is a verdict by an independent verifier on the user's reply. A disputed
    thread is actionable again.

A reply's `ai_review_verdict` is null, or {"verdict": "accept" | "disagree", "round": <n>} for a verdict. For a
top-level comment or a review body, `replies` are the current user's comments that carry the reply marker for it (see
utils.py).

A pulls/reviews entry is a review's own body, which can hold findings outside any inline thread: CodeRabbit lists its
follow-ups, nitpicks and outside-diff comments there. It is listed when it is a person's non-empty review body, or a
bot's that has such a section; a bot's other review bodies only summarize its inline threads. Its `id` is the review's.

Filtered out of the default output:
  - Resolved threads
  - Bot summary/walkthrough comments
  - Threads whose most recent comment is by the current user (already addressed), unless that comment is an AI
    review finding or a verdict disputing the reply to one
  - Top-level PR comments authored by the current user, unless they are an AI review finding
  - Top-level PR comments the current user has replied to (via post.py, which marks the reply), unless the last
    reply is a verdict disputing it
  - Review bodies the current user has replied to (via post.py, likewise)

`--all` brings back resolved and addressed threads and top-level comments, each with the `resolved` and `open` flags
that say where it stands, so the caller can tell three resolved threads from none at all. Bot summary comments and
the current user's own top-level comments stay out: a reply the user posted appears under the comment it answers.
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from utils import GH_TIMEOUT_SECONDS
from utils import VERDICT_DISAGREE
from utils import add_repo_arguments
from utils import enter_checkout
from utils import gh_graphql
from utils import gh_rest
from utils import map_line_between
from utils import owner_and_repo
from utils import parse_ai_review_finding
from utils import parse_ai_review_verdict
from utils import parse_issue_comment_reply
from utils import parse_review_reply
from utils import strip_markup

# Fetches only what we need to determine resolution: the root comment URL.
# We intentionally do NOT use databaseId here — it does not match the REST
# pulls/comments id that the replies endpoint requires.
RESOLVED_THREAD_URLS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          isResolved
          comments(first: 1) {
            nodes {
              url
            }
          }
        }
      }
    }
  }
}
"""


def fetch_current_user_login() -> str:
    return gh_rest("api", "user")["login"]


_BOT_LOGINS = frozenset({"coderabbitai[bot]", "copilot-pull-request-reviewer[bot]", "Copilot"})
# The sections in which CodeRabbit lists findings in a review's body, with no inline thread to hold them; a heading
# with a count of zero lists none
_REVIEW_BODY_FINDINGS_RE = re.compile(
    r"Follow-ups \([1-9]\d*\)|Nitpick comments \([1-9]\d*\)"
    r"|Outside diff range comments \([1-9]\d*\)|Additional comments: [1-9]\d*"
)


def _login_from_comment(c: dict[str, Any]) -> str:
    user = c.get("user")
    if user is None:
        return "ghost"
    login = user.get("login")
    if not isinstance(login, str):
        return "ghost"
    return login


def _author_is_bot(c: dict[str, Any]) -> bool:
    user = c.get("user")
    if user is None:
        return False
    if user.get("type") == "Bot":
        return True
    return user.get("login", "") in _BOT_LOGINS


def is_bot_pr_body_comment(c: dict[str, Any]) -> bool:
    if "user" not in c or c["user"] is None:
        return False
    return c["user"].get("login", "") in _BOT_LOGINS


def fetch_resolved_html_urls(*, owner: str, repo: str, pr_number: int) -> set[str]:
    """Return the HTML URL of the root comment from each resolved review thread.

    We match resolved threads to REST comments via html_url rather than by ID
    because GraphQL databaseId does not equal the REST pulls/comments id field,
    so ID-based matching produces 404s on the replies endpoint.
    """
    resolved: set[str] = set()
    after: str | None = None
    while True:
        variables: dict[str, str | int] = {"owner": owner, "repo": repo, "number": pr_number}
        if after is not None:
            variables["after"] = after
        data = gh_graphql(RESOLVED_THREAD_URLS_QUERY, variables)
        page = data["repository"]["pullRequest"]["reviewThreads"]
        for node in page["nodes"]:
            if node["isResolved"]:
                comments = node["comments"]["nodes"]
                if comments:
                    resolved.add(comments[0]["url"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return resolved


def _reply_entry(c: dict[str, Any]) -> dict[str, Any]:
    verdict = parse_ai_review_verdict(c["body"])
    return {
        "id": c["id"],
        "url": c.get("html_url", ""),
        "author": _login_from_comment(c),
        "author_is_bot": _author_is_bot(c),
        "body": c["body"],
        "body_text": strip_markup(c["body"]),
        "created_at": c["created_at"],
        "ai_review_verdict": None if verdict is None else {"verdict": verdict.verdict, "round": verdict.round},
    }


def _addressed_by_current_user(thread: dict[str, Any], current_user: str) -> bool:
    replies: list[dict[str, Any]] = thread["replies"]
    if replies:
        last = replies[-1]
        if last["author"] != current_user:
            return False
        # a verdict is posted under the current user's account too, and one disputing the reply reopens the thread
        verdict = last["ai_review_verdict"]
        if verdict is None:
            return True
        return verdict["verdict"] != VERDICT_DISAGREE
    # an AI review finding is posted under the current user's account but still awaits their response
    if thread["_ai_review"] is not None:
        return False
    return thread["author"] == current_user


def _ai_review_status(thread: dict[str, Any], current_user: str) -> str:
    replies: list[dict[str, Any]] = thread["replies"]
    if not replies:
        return "open"
    last = replies[-1]
    if last["author"] != current_user:
        return "open"
    verdict = last["ai_review_verdict"]
    if verdict is None:
        return "awaiting_verification"
    if verdict["verdict"] == VERDICT_DISAGREE:
        return "disputed"
    return "accepted"


def _line_anchor(c: dict[str, Any]) -> tuple[str, int, str] | None:
    """Return the path, line and commit an inline comment was made on, or None for a file-level or incomplete one."""
    path = c.get("path")
    original_line = c.get("original_line")
    original_commit = c.get("original_commit_id")
    if c.get("subject_type") == "file":
        return None
    if path is None:
        return None
    if original_line is None:
        return None
    if original_commit is None:
        return None
    return path, original_line, original_commit


def _current_position(c: dict[str, Any]) -> tuple[int | None, bool | None]:
    """Return where an inline comment's original line is at HEAD, and whether that line has changed since.

    Both are None for a file-level comment, or when the commit the comment was made on isn't available locally.
    """
    anchor = _line_anchor(c)
    if anchor is None:
        return None, None
    path, original_line, original_commit = anchor
    try:
        current_line = map_line_between(path=path, line=original_line, from_commit=original_commit, to_commit="HEAD")
    except subprocess.CalledProcessError:
        return None, None
    if current_line is None:
        return None, True
    return current_line, False


def _collect_thread_roots(pulls_raw: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return root comments (no in_reply_to_id) keyed by id, with empty replies lists."""
    roots: dict[int, dict[str, Any]] = {}
    for c in pulls_raw:
        if c.get("in_reply_to_id") is None:
            subject_type = c.get("subject_type")
            current_line, line_changed = _current_position(c)
            roots[c["id"]] = {
                "id": c["id"],
                "type": "pulls/comments",
                "url": c.get("html_url", ""),
                "author": _login_from_comment(c),
                "author_is_bot": _author_is_bot(c),
                "body": c["body"],
                "body_text": strip_markup(c["body"]),
                "created_at": c["created_at"],
                "path": c.get("path"),
                # a file-level comment is about the whole file, so any line GitHub reports for it is not a position
                "line": None if subject_type == "file" else c.get("line") or c.get("original_line"),
                "subject_type": subject_type,
                # GitHub nulls `line` once a later commit changes the commented line
                "outdated": subject_type != "file" and c.get("line") is None,
                "original_line": c.get("original_line"),
                "original_commit_id": c.get("original_commit_id"),
                "current_line": current_line,
                "line_changed": line_changed,
                "_ai_review": parse_ai_review_finding(c["body"]),
                "replies": [],
            }
    return roots


def _resolve_root_id(
    parent_id: int,
    roots: dict[int, dict[str, Any]],
    all_pulls: dict[int, dict[str, Any]],
) -> int | None:
    """Walk up the in_reply_to_id chain until a known root is found. Return None if broken."""
    root_id = parent_id
    seen: set[int] = set()
    while root_id not in roots and root_id not in seen:
        seen.add(root_id)
        parent = all_pulls.get(root_id)
        if parent is None:
            return None
        root_id = parent.get("in_reply_to_id", root_id)
    return root_id if root_id in roots else None


def _attach_replies(pulls_raw: list[dict[str, Any]], roots: dict[int, dict[str, Any]]) -> None:
    """Append each non-root comment as a reply on its thread root."""
    all_pulls: dict[int, dict[str, Any]] = {c["id"]: c for c in pulls_raw}
    for c in pulls_raw:
        parent_id = c.get("in_reply_to_id")
        if parent_id is None:
            continue
        root_id = _resolve_root_id(parent_id, roots, all_pulls)
        if root_id is None:
            continue
        roots[root_id]["replies"].append(_reply_entry(c))
    for t in roots.values():
        replies: list[dict[str, Any]] = t["replies"]
        replies.sort(key=lambda r: r["created_at"])


def _all_pulls_threads(pulls_raw: list[dict[str, Any]], resolved_urls: set[str]) -> list[dict[str, Any]]:
    """Group inline review comments into threads, each marked with whether it is resolved."""
    roots = _collect_thread_roots(pulls_raw)
    _attach_replies(pulls_raw, roots)
    return [{**t, "resolved": t["url"] in resolved_urls} for t in roots.values()]


def _marked_replies(
    issues_raw: list[dict[str, Any]], *, current_user: str, parse_marker: Callable[[str], int | None]
) -> dict[int, list[dict[str, Any]]]:
    """Map each answered id to the current user's top-level comments whose marker names it, oldest first.

    GitHub has no threads for top-level comments, so a reply to one (or to a review body) is a top-level comment
    carrying a marker with the answered id. `parse_marker` reads that id from a comment's body, or returns None for
    a comment without the marker; such comments, and every other user's, are left out.
    """
    replies: dict[int, list[dict[str, Any]]] = {}
    for c in issues_raw:
        if _login_from_comment(c) != current_user:
            continue
        replied_id = parse_marker(c["body"])
        if replied_id is not None:
            replies.setdefault(replied_id, []).append(_reply_entry(c))
    for chain in replies.values():
        chain.sort(key=lambda r: r["created_at"])
    return replies


def _all_flat_issues(issues_raw: list[dict[str, Any]], current_user: str) -> list[dict[str, Any]]:
    """Project top-level PR comments, leaving out bot summaries and the current user's own comments.

    The current user's AI review findings are kept: they are posted under that account but still await a response.
    Their replies and verdicts are attached to the comment they answer instead.
    """
    replies = _marked_replies(issues_raw, current_user=current_user, parse_marker=parse_issue_comment_reply)
    flat: list[dict[str, Any]] = []
    for c in issues_raw:
        if is_bot_pr_body_comment(c):
            continue
        ai_review = parse_ai_review_finding(c["body"])
        if _login_from_comment(c) == current_user and ai_review is None:
            continue
        flat.append(
            {
                "id": c["id"],
                "type": "issues/comments",
                "url": c.get("html_url", ""),
                "author": _login_from_comment(c),
                "author_is_bot": _author_is_bot(c),
                "body": c["body"],
                "body_text": strip_markup(c["body"]),
                "created_at": c["created_at"],
                "path": None,
                "line": None,
                "subject_type": None,
                "outdated": False,
                "original_line": None,
                "original_commit_id": None,
                "current_line": None,
                "line_changed": None,
                "resolved": False,
                "_ai_review": ai_review,
                "replies": replies.get(c["id"], []),
            }
        )
    return flat


def _review_body_to_answer(*, review: dict[str, Any], current_user: str) -> bool:
    """Return whether a review's own body holds something to answer, apart from the review's inline threads.

    A person's review body says something whenever it isn't empty. A bot's mostly summarizes its inline comments,
    which are threads of their own, so it counts only when it lists findings that have no thread.
    """
    if review.get("submitted_at") is None:
        return False
    if _login_from_comment(review) == current_user:
        return False
    if not strip_markup(review.get("body") or ""):
        return False
    if not _author_is_bot(review):
        return True
    if _REVIEW_BODY_FINDINGS_RE.search(strip_markup(review["body"])) is None:
        return False
    return True


def _all_review_bodies(
    *, reviews_raw: list[dict[str, Any]], issues_raw: list[dict[str, Any]], current_user: str
) -> list[dict[str, Any]]:
    """Project each review body that holds something to answer, with the current user's replies to it."""
    replies = _marked_replies(issues_raw, current_user=current_user, parse_marker=parse_review_reply)
    entries: list[dict[str, Any]] = []
    for r in reviews_raw:
        if not _review_body_to_answer(review=r, current_user=current_user):
            continue
        entries.append(
            {
                "id": r["id"],
                "type": "pulls/reviews",
                "url": r.get("html_url", ""),
                "author": _login_from_comment(r),
                "author_is_bot": _author_is_bot(r),
                "body": r["body"],
                "body_text": strip_markup(r["body"]),
                "created_at": r["submitted_at"],
                "path": None,
                "line": None,
                "subject_type": None,
                "outdated": False,
                "original_line": None,
                "original_commit_id": r.get("commit_id"),
                "current_line": None,
                "line_changed": None,
                "resolved": False,
                "_ai_review": None,
                "replies": replies.get(r["id"], []),
            }
        )
    return entries


def _ai_review_finding_comment_ids(comments_raw: list[dict[str, Any]]) -> dict[str, int]:
    """Map each AI review finding ID on the PR to the comment holding it, whether or not it is still open.

    Only thread roots and top-level comments can hold a finding, so replies are skipped.
    """
    comment_ids: dict[str, int] = {}
    for c in comments_raw:
        if c.get("in_reply_to_id") is not None:
            continue
        finding = parse_ai_review_finding(c["body"])
        if finding is not None:
            comment_ids[finding.finding_id] = c["id"]
    return comment_ids


def _with_ai_review(
    entries: list[dict[str, Any]], *, open_ids: set[int], finding_comment_ids: dict[str, int], current_user: str
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for e in entries:
        finding = e["_ai_review"]
        ai_review = None
        if finding is not None:
            related: list[dict[str, Any]] = []
            for related_id in finding.related_ids:
                comment_id = finding_comment_ids.get(related_id)
                related.append({"finding_id": related_id, "comment_id": comment_id, "open": comment_id in open_ids})
            ai_review = {
                "finding_id": finding.finding_id,
                "related": related,
                "status": _ai_review_status(e, current_user),
                "verdict_rounds": sum(1 for r in e["replies"] if r["ai_review_verdict"] is not None),
            }
        projected.append(
            {**{k: v for k, v in e.items() if k != "_ai_review"}, "open": e["id"] in open_ids, "ai_review": ai_review}
        )
    return projected


def fetch(*, owner: str, repo: str, pr_number: int, current_user: str) -> list[dict[str, Any]]:
    """Return every thread and top-level comment on the PR, each marked with whether it is actionable (`open`)."""
    # GitHub exposes two separate comment APIs for pull requests:
    #
    # - pulls/comments: inline review comments attached to specific lines of code.
    #   These can form threads — a root comment plus replies. Each reply carries
    #   an `in_reply_to_id` pointing to its parent.
    #   Resolved threads are excluded using GraphQL reviewThreads.isResolved, since
    #   the REST API does not expose thread resolution status. We use REST IDs for
    #   the thread structure because they are what the replies endpoint accepts.
    #
    # - issues/comments: general comments on the PR conversation (not tied to a
    #   line). These are flat — GitHub has no threading or resolved concept for them.
    #
    # - pulls/reviews: each review's own body, which can hold findings outside any
    #   inline thread (CodeRabbit's follow-ups, nitpicks and outside-diff comments).
    #   Flat like issues/comments.
    resolved_urls = fetch_resolved_html_urls(owner=owner, repo=repo, pr_number=pr_number)

    pulls_raw: list[dict[str, Any]] = gh_rest("api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments", "--paginate")
    issues_raw: list[dict[str, Any]] = gh_rest("api", f"repos/{owner}/{repo}/issues/{pr_number}/comments", "--paginate")
    reviews_raw: list[dict[str, Any]] = gh_rest("api", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews", "--paginate")

    everything = (
        _all_pulls_threads(pulls_raw, resolved_urls)
        + _all_flat_issues(issues_raw, current_user)
        + _all_review_bodies(reviews_raw=reviews_raw, issues_raw=issues_raw, current_user=current_user)
    )
    open_ids = {e["id"] for e in everything if not e["resolved"] and not _addressed_by_current_user(e, current_user)}
    combined = _with_ai_review(
        everything,
        open_ids=open_ids,
        finding_comment_ids=_ai_review_finding_comment_ids(pulls_raw + issues_raw),
        current_user=current_user,
    )
    combined.sort(key=lambda x: x["created_at"])
    return combined


def select(
    entries: list[dict[str, Any]], *, all_entries: bool, needs_verification: bool, thread_id: int | None
) -> list[dict[str, Any]]:
    if thread_id is not None:
        return [e for e in entries if e["id"] == thread_id]
    if all_entries:
        return entries
    if needs_verification:
        return [
            e
            for e in entries
            if not e["resolved"] and e["ai_review"] is not None and e["ai_review"]["status"] == "awaiting_verification"
        ]
    return [e for e in entries if e["open"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("pr_number", help="PR number, with or without a leading #")
    selection = parser.add_mutually_exclusive_group()
    _ = selection.add_argument(
        "--needs-verification",
        action="store_true",
        help="list AI review findings whose latest reply from you has no verdict yet",
    )
    _ = selection.add_argument(
        "--thread", type=int, default=None, help="return only this thread or top-level comment, whatever its state"
    )
    _ = selection.add_argument(
        "--all",
        action="store_true",
        help="list resolved and addressed threads and comments too, with their flags",
    )
    add_repo_arguments(parser)
    args = parser.parse_args()
    enter_checkout(args.checkout)

    pr_number_raw = args.pr_number.strip().lstrip("#")
    try:
        pr_number = int(pr_number_raw)
    except ValueError:
        _ = sys.stderr.write(f"Invalid PR number: {pr_number_raw}\n")
        sys.exit(1)

    owner, repo = owner_and_repo(repo=args.repo)

    try:
        current_user = fetch_current_user_login()
        comments = select(
            fetch(owner=owner, repo=repo, pr_number=pr_number, current_user=current_user),
            all_entries=args.all,
            needs_verification=args.needs_verification,
            thread_id=args.thread,
        )
        _ = sys.stdout.write(json.dumps(comments, indent=2) + "\n")
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"gh api error: {e.stderr}\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(f"gh api timed out after {GH_TIMEOUT_SECONDS}s\n")
        sys.exit(1)
    except RuntimeError as e:
        _ = sys.stderr.write(f"{e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
