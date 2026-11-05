#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Build the prompt for each ai-review-verifier to start, for the address-pr-comments skill.

Usage:
  verifier_prompt.py --pr <number> --comment-id <root id> ...   the replies just posted
  verifier_prompt.py --pr <number> --all-awaiting               every reply awaiting a verdict (start of a run only)
Either form takes --checkout <path> when the PR belongs to that checkout of another repo.

A prompt holds identifiers only: the finding, its root comment, the reply to judge, the commits that reply links and
the PR head, plus the checkout's absolute path when there is one, and the commands that read the thread and post the
verdict. That keeps the verifier independent of the agent that wrote the reply, which never adds its own view. Use
--all-awaiting only when no verifier from this run is still working: one still running has not posted yet, so its
thread still awaits a verdict and would get a second verifier.

Prints JSON:
  {"verifiers": [{"comment_id", "finding_id", "description", "prompt"}], "skipped": [{"comment_id", "reason"}]}
A thread is skipped when it is not an AI review finding, has no reply awaiting a verdict, or has had
MAX_VERDICT_ROUNDS verdicts, after which it is left to the user.
"""

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from utils import GH_TIMEOUT_SECONDS
from utils import MAX_VERDICT_ROUNDS
from utils import enter_checkout
from utils import gh_rest
from utils import owner_repo_from_remote

# The verifier runs from the repo root these skills live in, and is given these scripts' commands in its prompt, so
# that its instructions name no script and cannot go stale when one moves.
REPO_ROOT = Path(__file__).resolve().parents[3]
READ_SCRIPT = Path(__file__).resolve().parent.parent / "pr-comments" / "read.py"
POST_VERDICT_SCRIPT = Path(__file__).resolve().parent / "post_verdict.py"


def _command(script: Path, *args: str) -> str:
    return shlex.join([str(script.relative_to(REPO_ROOT)), *args])


def _fail(message: str) -> NoReturn:
    _ = sys.stderr.write(f"{message}\n")
    sys.exit(1)


def _fetch(*, pr: int, args: list[str]) -> list[dict[str, Any]]:
    result = subprocess.run(  # noqa: S603 — the pr-comments skill's script, with every value a separate argument
        [str(READ_SCRIPT), str(pr), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=GH_TIMEOUT_SECONDS * 4,
    )
    if result.returncode != 0:
        _fail(f"read.py failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _reply_to_judge(thread: dict[str, Any]) -> dict[str, Any] | None:
    """Return the latest reply that isn't a verdict: the one a verifier would judge."""
    for reply in reversed(thread["replies"]):
        if reply["ai_review_verdict"] is None:
            return reply
    return None


def _linked_commits(body: str, *, repo: str) -> list[str]:
    # a reply can link a commit in the PR's repo as .../pull/<pr>/commits/<sha>, .../pull/<pr>/changes/<sha> (GitHub
    # serves both views) or a plain .../commit/<sha>; a commit in another repo can't be read from the PR's checkout
    linked_commit_re = re.compile(
        rf"https://github\.com/{re.escape(repo)}/(?:pull/\d+/(?:changes|commits)|commit)/(?P<sha>[0-9a-f]{{40}})\b"
    )
    commits: list[str] = []
    for match in linked_commit_re.finditer(body):
        if match.group("sha") not in commits:
            commits.append(match.group("sha"))
    return commits


def _verifier(*, repo: str, pr: int, thread: dict[str, Any], head: str, checkout: Path | None) -> dict[str, Any]:
    ai_review = thread["ai_review"]
    if ai_review is None:
        return {"comment_id": thread["id"], "reason": "not an AI review finding"}
    if ai_review["verdict_rounds"] >= MAX_VERDICT_ROUNDS:
        return {
            "comment_id": thread["id"],
            "reason": f"{ai_review['finding_id']} has had {ai_review['verdict_rounds']} verdicts; it is the user's call",
        }
    if ai_review["status"] != "awaiting_verification":
        return {"comment_id": thread["id"], "reason": f"no reply awaiting a verdict (status: {ai_review['status']})"}
    reply = _reply_to_judge(thread)
    if reply is None:
        return {"comment_id": thread["id"], "reason": "no reply to judge"}
    commits = _linked_commits(reply["body"], repo=repo)
    lines = [
        f"PR: {pr}",
        f"Finding: {ai_review['finding_id']}, root comment {thread['id']} ({thread['type']})",
        f"Reply to judge: {reply['url']}",
        f"Commits the reply links: {', '.join(commits) if commits else 'none'}",
        f"PR head after the push: {head}",
    ]
    checkout_args = [] if checkout is None else ["--checkout", str(checkout)]
    if checkout is not None:
        lines.append(f"Checkout of the PR's repo: {checkout}")
    read_command = _command(READ_SCRIPT, str(pr), "--thread", str(thread["id"]), *checkout_args)
    post_command = _command(POST_VERDICT_SCRIPT, "--pr", str(pr), "--comment-id", str(thread["id"]), *checkout_args)
    lines += [f"Read the thread: {read_command}", f"Post the verdict: {post_command}"]
    return {
        "comment_id": thread["id"],
        "finding_id": ai_review["finding_id"],
        "description": f"Verify reply to {ai_review['finding_id']}",
        "prompt": "\n".join(lines),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--pr", required=True, type=int)
    selection = parser.add_mutually_exclusive_group(required=True)
    _ = selection.add_argument("--comment-id", nargs="+", type=int, help="root IDs of the threads just replied to")
    _ = selection.add_argument("--all-awaiting", action="store_true", help="every reply awaiting a verdict")
    _ = parser.add_argument("--checkout", type=Path, default=None, help="a checkout of the PR's repo, if not this one")
    args = parser.parse_args()
    enter_checkout(args.checkout)
    # absolute, since the verifier runs from the originating repo whatever directory this ran from
    checkout = None if args.checkout is None else Path.cwd()

    owner, repo = owner_repo_from_remote()
    try:
        head = gh_rest("api", f"repos/{owner}/{repo}/pulls/{args.pr}")["head"]["sha"]
    except subprocess.CalledProcessError as e:
        _fail(f"gh api error: {e.stderr}")
    if args.all_awaiting:
        threads = _fetch(pr=args.pr, args=["--needs-verification"])
    else:
        threads = [
            thread
            # a repeated id would start two verifiers on one thread, which could post two verdicts
            for comment_id in dict.fromkeys(args.comment_id)
            for thread in _fetch(pr=args.pr, args=["--thread", str(comment_id)])
        ]
        missing = sorted(set(args.comment_id) - {thread["id"] for thread in threads})
        if missing:
            _fail(f"Not a thread or top-level comment on PR #{args.pr}: {', '.join(map(str, missing))}")

    verifiers: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for thread in threads:
        result = _verifier(repo=f"{owner}/{repo}", pr=args.pr, thread=thread, head=head, checkout=checkout)
        if "prompt" in result:
            verifiers.append(result)
        else:
            skipped.append(result)
    _ = sys.stdout.write(json.dumps({"verifiers": verifiers, "skipped": skipped}, indent=2) + "\n")


if __name__ == "__main__":
    main()
