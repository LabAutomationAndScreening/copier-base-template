#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Resolve one inline review thread on a PR, for the pr-comments skill.

Usage:
  resolve.py <pr_number> --thread <root comment id> --last-comment <comment id> [--repo OWNER/NAME | --checkout PATH]

GitHub's REST API cannot resolve a thread, so the thread is found among the PR's GraphQL review threads by its root
comment's URL and the resolveReviewThread mutation is run on it. Prints `Resolved: <root comment url>`, or
`Already resolved: <root comment url>` without changing anything.

`--last-comment` is the thread's newest comment when the user approved resolving it. The user may take a while to
answer, and a resolved thread drops out of read.py's default output, so a comment posted in the meantime would never be
triaged. When the thread's newest comment is no longer that one, nothing is resolved and the script exits 1 naming both.
The mutation has no such precondition, so a comment posted between reading the threads and resolving is caught from
the mutation's own response instead: the thread is reopened and the script exits 1 the same way.
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import gh_graphql
from utils import gh_rest
from utils import parse_pr_arguments
from utils import print_or_exit_on_gh_error
from utils import review_threads

RESOLVE_MUTATION = """
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread {
      isResolved
      comments(last: 1) {
        nodes {
          url
        }
      }
    }
  }
}
"""

UNRESOLVE_MUTATION = """
mutation($threadId: ID!) {
  unresolveReviewThread(input: {threadId: $threadId}) {
    thread {
      isResolved
    }
  }
}
"""


class ThreadNotFoundError(RuntimeError):
    def __init__(self, *, pr_number: int, root_url: str):
        super().__init__(f"PR #{pr_number} has no review thread whose root comment is {root_url}")


class ThreadChangedSinceApprovalError(RuntimeError):
    def __init__(self, *, root_url: str, last_url: str, approved_last_url: str):
        super().__init__(
            f"Not resolved: the newest comment in {root_url} is {last_url}, not the approved {approved_last_url}"
        )


class ThreadLeftResolvedError(RuntimeError):
    def __init__(self, *, root_url: str, last_url: str, approved_last_url: str, cause: str):
        super().__init__(
            f"Resolved {root_url}, but its newest comment is {last_url}, not the approved {approved_last_url}, and "
            f"reopening it failed, so reopen it by hand: {cause}"
        )


class ThreadNotResolvedError(RuntimeError):
    def __init__(self, *, root_url: str):
        super().__init__(f"GitHub accepted the request but still reports the thread at {root_url} as unresolved")


def resolve(*, owner: str, repo: str, pr_number: int, root_comment_id: int, last_comment_id: int) -> str:
    root_url: str = gh_rest("api", f"repos/{owner}/{repo}/pulls/comments/{root_comment_id}")["html_url"]
    approved_last_url: str = gh_rest("api", f"repos/{owner}/{repo}/pulls/comments/{last_comment_id}")["html_url"]
    for thread in review_threads(owner=owner, repo=repo, pr_number=pr_number):
        if thread.root_url != root_url:
            continue
        if thread.is_resolved:
            return f"Already resolved: {root_url}"
        if thread.last_url != approved_last_url:
            raise ThreadChangedSinceApprovalError(
                root_url=root_url, last_url=thread.last_url, approved_last_url=approved_last_url
            )
        resolved = gh_graphql(RESOLVE_MUTATION, {"threadId": thread.graphql_id})["resolveReviewThread"]["thread"]
        if not resolved["isResolved"]:
            raise ThreadNotResolvedError(root_url=root_url)
        last_url_when_resolved: str = resolved["comments"]["nodes"][0]["url"]
        if last_url_when_resolved != approved_last_url:
            _reopen(
                thread_id=thread.graphql_id,
                root_url=root_url,
                last_url=last_url_when_resolved,
                approved_last_url=approved_last_url,
            )
            raise ThreadChangedSinceApprovalError(
                root_url=root_url, last_url=last_url_when_resolved, approved_last_url=approved_last_url
            )
        return f"Resolved: {root_url}"
    raise ThreadNotFoundError(pr_number=pr_number, root_url=root_url)


def _reopen(*, thread_id: str, root_url: str, last_url: str, approved_last_url: str) -> None:
    try:
        _ = gh_graphql(UNRESOLVE_MUTATION, {"threadId": thread_id})
    except subprocess.CalledProcessError as e:
        raise ThreadLeftResolvedError(
            root_url=root_url, last_url=last_url, approved_last_url=approved_last_url, cause=f"gh api error: {e.stderr}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ThreadLeftResolvedError(
            root_url=root_url, last_url=last_url, approved_last_url=approved_last_url, cause="gh api timed out"
        ) from e
    except RuntimeError as e:
        raise ThreadLeftResolvedError(
            root_url=root_url, last_url=last_url, approved_last_url=approved_last_url, cause=str(e)
        ) from e


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("pr_number", help="PR number, with or without a leading #")
    _ = parser.add_argument(
        "--thread", type=int, required=True, help="the thread's root comment ID, as read.py gives it"
    )
    _ = parser.add_argument(
        "--last-comment",
        type=int,
        required=True,
        help="ID of the thread's newest comment when the user approved resolving it; a newer one blocks resolving",
    )
    pr = parse_pr_arguments(parser)
    print_or_exit_on_gh_error(
        lambda: resolve(
            owner=pr.owner,
            repo=pr.repo,
            pr_number=pr.pr_number,
            root_comment_id=pr.args.thread,
            last_comment_id=pr.args.last_comment,
        )
    )


if __name__ == "__main__":
    main()
