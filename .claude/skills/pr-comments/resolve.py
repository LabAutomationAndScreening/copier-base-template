#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Resolve one inline review thread on a PR, for the pr-comments skill.

Usage:
  resolve.py <pr_number> --thread <root comment id> [--repo OWNER/NAME | --checkout PATH]

GitHub's REST API cannot resolve a thread, so the thread is found among the PR's GraphQL review threads by its root
comment's URL and the resolveReviewThread mutation is run on it. Prints `Resolved: <root comment url>`, or
`Already resolved: <root comment url>` without changing anything.
"""

import argparse
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
    }
  }
}
"""


class ThreadNotFoundError(RuntimeError):
    def __init__(self, *, pr_number: int, root_url: str):
        super().__init__(f"PR #{pr_number} has no review thread whose root comment is {root_url}")


class ThreadNotResolvedError(RuntimeError):
    def __init__(self, *, root_url: str):
        super().__init__(f"GitHub accepted the request but still reports the thread at {root_url} as unresolved")


def resolve(*, owner: str, repo: str, pr_number: int, root_comment_id: int) -> str:
    root_url: str = gh_rest("api", f"repos/{owner}/{repo}/pulls/comments/{root_comment_id}")["html_url"]
    for thread in review_threads(owner=owner, repo=repo, pr_number=pr_number):
        if thread.root_url != root_url:
            continue
        if thread.is_resolved:
            return f"Already resolved: {root_url}"
        result = gh_graphql(RESOLVE_MUTATION, {"threadId": thread.graphql_id})
        if not result["resolveReviewThread"]["thread"]["isResolved"]:
            raise ThreadNotResolvedError(root_url=root_url)
        return f"Resolved: {root_url}"
    raise ThreadNotFoundError(pr_number=pr_number, root_url=root_url)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("pr_number", help="PR number, with or without a leading #")
    _ = parser.add_argument(
        "--thread", type=int, required=True, help="the thread's root comment ID, as read.py gives it"
    )
    pr = parse_pr_arguments(parser)
    print_or_exit_on_gh_error(
        lambda: resolve(owner=pr.owner, repo=pr.repo, pr_number=pr.pr_number, root_comment_id=pr.args.thread)
    )


if __name__ == "__main__":
    main()
