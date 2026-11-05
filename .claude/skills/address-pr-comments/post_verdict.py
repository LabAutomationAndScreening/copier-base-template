#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Post the ai-review-verifier agent's verdict on a reply to an AI review finding, and resolve the thread on accept.

Usage:
  post_verdict.py --pr <number> --comment-id <root id> --head <sha> --verdict accept|disagree --model <model id>
                  [--effort <level>] [--dry-run] [--checkout <path>] < verdict.md

The verdict text is read from stdin. The posted comment opens with a line naming the verdict and the model (and
effort level, when given) that reached it, and carries a hidden marker so read.py can tell the verdict
apart from the reply it judges: a disagreement reopens the thread for /address-pr-comments.

On accept, an inline thread is resolved, unless someone other than the current user (and other than a bot) has
replied in it: once another person has joined a thread, resolving it is their call. Top-level PR comments cannot be
resolved on GitHub, so for those the verdict is only posted.

Refuses to post when the comment is not an AI review finding, when its latest reply is not one from the current
user awaiting a verdict (nothing to judge, already judged, or someone else has the last word), or when the thread
already has MAX_VERDICT_ROUNDS verdicts, at which point the thread is left to the user. It also refuses when the PR's
head is no longer --head, the commit the verdict was reached on: a later push may have changed what the reply relies
on, so a new verifier judges the new head.

With --dry-run, prints the comment and what would happen to the thread, and posts nothing.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from utils import GH_TIMEOUT_SECONDS
from utils import MAX_VERDICT_ROUNDS
from utils import VERDICT_ACCEPT
from utils import VERDICT_DISAGREE
from utils import ai_review_verdict_marker
from utils import describe_model
from utils import enter_checkout
from utils import gh_graphql
from utils import gh_rest
from utils import issue_comment_reply_marker
from utils import owner_repo_from_remote

FOOTER = (
    "<sub>Checked by an AI agent independent of the one that wrote the reply above, and posted under the account of "
    "the person whose agent wrote that reply, without their review.</sub>"
)

THREAD_IDS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id comments(first: 1) { nodes { url } } }
      }
    }
  }
}
"""
RESOLVE_THREAD = """
mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) { thread { isResolved } } }
"""


class RefusedError(Exception):
    pass


def _fail(message: str) -> None:
    _ = sys.stderr.write(f"{message}\n")
    sys.exit(1)


def _fetch_thread(*, pr: int, comment_id: int) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 — the script is the pr-comments skill's, and every value is a separate argument
        [str(Path(__file__).parent.parent / "pr-comments" / "read.py"), str(pr), "--thread", str(comment_id)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=GH_TIMEOUT_SECONDS * 4,
    )
    threads = json.loads(result.stdout)
    if len(threads) != 1:
        raise RefusedError(f"comment {comment_id} is not a thread or top-level comment on PR #{pr}")
    return threads[0]


def other_participants(*, thread: dict[str, Any], current_user: str) -> list[str]:
    """Return the people, other than the current user, who have replied in the thread.

    The root comment is an AI review finding, so whoever posted it is not taking part in the discussion, and bots
    are not people.
    """
    others: list[str] = []
    for reply in thread["replies"]:
        if reply["author_is_bot"]:
            continue
        if reply["author"] == current_user:
            continue
        if reply["author"] not in others:
            others.append(reply["author"])
    return others


def _check_can_post(thread: dict[str, Any]) -> dict[str, Any]:
    ai_review = thread["ai_review"]
    if ai_review is None:
        raise RefusedError(f"comment {thread['id']} is not an AI review finding, so there is no reply to verify")
    if thread["resolved"]:
        raise RefusedError(f"the thread for {ai_review['finding_id']} is already resolved")
    if ai_review["verdict_rounds"] >= MAX_VERDICT_ROUNDS:
        raise RefusedError(
            f"{ai_review['finding_id']} already has {ai_review['verdict_rounds']} verdicts, so it is left to the user"
        )
    if ai_review["status"] != "awaiting_verification":
        raise RefusedError(
            f"{ai_review['finding_id']} has no reply awaiting a verdict (status: {ai_review['status']}); either "
            "nothing has been replied yet, it was already judged, or someone else has the last word"
        )
    return ai_review


def _check_head(*, owner: str, repo: str, pr: int, head: str) -> None:
    current = gh_rest("api", f"repos/{owner}/{repo}/pulls/{pr}")["head"]["sha"]
    if current != head:
        raise RefusedError(
            f"the PR head moved from {head}, where this verdict was reached, to {current}; start a new verifier "
            "to judge the reply at the new head"
        )


def _thread_node_id(*, owner: str, repo: str, pr: int, root_url: str) -> str | None:
    after: str | None = None
    while True:
        variables: dict[str, str | int | bool] = {"owner": owner, "repo": repo, "number": pr}
        if after is not None:
            variables["after"] = after
        page = gh_graphql(THREAD_IDS_QUERY, variables)["repository"]["pullRequest"]["reviewThreads"]
        for node in page["nodes"]:
            comments = node["comments"]["nodes"]
            if comments and comments[0]["url"] == root_url:
                return node["id"]
        if not page["pageInfo"]["hasNextPage"]:
            return None
        after = page["pageInfo"]["endCursor"]


def _resolve_posted_thread(*, owner: str, repo: str, pr: int, root_url: str) -> bool:
    """Resolve the thread a verdict was just posted on, and return whether it is now resolved.

    The verdict is already on GitHub by now, so a failure here is a warning, not an error: the caller still prints the
    posted verdict, and a retry would be refused because the thread no longer awaits verification.
    """
    try:
        thread_id = _thread_node_id(owner=owner, repo=repo, pr=pr, root_url=root_url)
        if thread_id is None:
            _ = sys.stderr.write(f"Posted, but could not find the review thread for {root_url} to resolve.\n")
            return False
        return gh_graphql(RESOLVE_THREAD, {"threadId": thread_id})["resolveReviewThread"]["thread"]["isResolved"]
    except subprocess.CalledProcessError as e:
        _ = sys.stderr.write(f"Posted, but could not resolve the thread: {e.stderr}\n")
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write("Posted, but resolving the thread timed out.\n")
    except RuntimeError as e:
        _ = sys.stderr.write(f"Posted, but could not resolve the thread: {e}\n")
    return False


OUTCOME_BY_RESOLUTION = {
    "resolve": "**accepted**, so this thread is resolved.",
    "leave_to_others": "**accepted**. Someone else has joined this thread, so resolving it is left to them.",
    "cannot_resolve": "**accepted**.",
    "keep_open": "**not settled**, so this thread stays open for another reply.",
}


def render_verdict(*, marker: str, verifier: str, resolution: str, text: str) -> str:
    banner = f"> 🤖 **AI review verification** by {verifier}: {OUTCOME_BY_RESOLUTION[resolution]}"
    return f"{marker}\n{banner}\n\n{text.strip()}\n\n{FOOTER}"


def _resolution(*, verdict: str, thread: dict[str, Any], others: list[str]) -> str:
    if verdict == VERDICT_DISAGREE:
        return "keep_open"
    if thread["type"] != "pulls/comments":
        return "cannot_resolve"
    if others:
        return "leave_to_others"
    return "resolve"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--pr", required=True, type=int)
    _ = parser.add_argument("--comment-id", required=True, type=int, help="the AI review finding's root comment ID")
    _ = parser.add_argument("--head", required=True, help="the PR head commit the verdict was reached on")
    _ = parser.add_argument("--verdict", required=True, choices=[VERDICT_ACCEPT, VERDICT_DISAGREE])
    _ = parser.add_argument("--model", required=True, help="the exact model ID of the agent that reached the verdict")
    _ = parser.add_argument("--effort", default=None, help="the effort level it ran at, when known")
    _ = parser.add_argument("--dry-run", action="store_true", help="print the comment and the outcome, post nothing")
    _ = parser.add_argument("--checkout", type=Path, default=None, help="a checkout of the PR's repo, if not this one")
    args = parser.parse_args()
    enter_checkout(args.checkout)

    text = sys.stdin.read()
    if not text.strip():
        _fail("The verdict text (stdin) is empty.")

    owner, repo = owner_repo_from_remote()
    try:
        current_user = gh_rest("api", "user")["login"]
        thread = _fetch_thread(pr=args.pr, comment_id=args.comment_id)
        ai_review = _check_can_post(thread)
        _check_head(owner=owner, repo=repo, pr=args.pr, head=args.head)
        others = other_participants(thread=thread, current_user=current_user)
        resolution = _resolution(verdict=args.verdict, thread=thread, others=others)
        body = render_verdict(
            marker=ai_review_verdict_marker(
                finding_id=ai_review["finding_id"], verdict=args.verdict, round_number=ai_review["verdict_rounds"] + 1
            ),
            verifier=describe_model(model=args.model, effort=args.effort),
            resolution=resolution,
            text=text,
        )
        if args.dry_run:
            _ = sys.stdout.write(
                json.dumps({"resolution": resolution, "other_participants": others, "body": body}, indent=2) + "\n"
            )
            return

        if thread["type"] == "pulls/comments":
            endpoint = f"repos/{owner}/{repo}/pulls/{args.pr}/comments/{args.comment_id}/replies"
        else:
            endpoint = f"repos/{owner}/{repo}/issues/{args.pr}/comments"
            body = f"{body}\n{issue_comment_reply_marker(args.comment_id)}\n"
        posted = gh_rest("api", endpoint, "--method", "POST", "--raw-field", f"body={body}")

        resolved = False
        if resolution == "resolve":
            resolved = _resolve_posted_thread(owner=owner, repo=repo, pr=args.pr, root_url=thread["url"])
        _ = sys.stdout.write(
            json.dumps(
                {
                    "url": posted.get("html_url"),
                    "finding_id": ai_review["finding_id"],
                    "verdict": args.verdict,
                    "round": ai_review["verdict_rounds"] + 1,
                    "resolution": resolution,
                    "resolved": resolved,
                },
                indent=2,
            )
            + "\n"
        )
    except RefusedError as e:
        _fail(f"Not posting: {e}.")
    except subprocess.CalledProcessError as e:
        _fail(f"gh api error: {e.stderr}")
    except subprocess.TimeoutExpired:
        _fail("gh api timed out")
    except RuntimeError as e:
        _fail(str(e))


if __name__ == "__main__":
    main()
