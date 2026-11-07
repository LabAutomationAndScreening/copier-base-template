#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Push a batch's commits, then post its replies, in that order, for the address-pr-comments skill.

Usage:
  push_and_post.py --pr <number> [--inline <comment id> ...] [--top-level <comment id> ...] [--review <review id> ...]
                   [--checkout <path>]

--inline takes the root IDs of inline review threads (pulls/comments), --top-level the IDs of top-level PR comments
(issues/comments) and --review the IDs of reviews whose own body is answered (pulls/reviews). Each reply is read from <repo_root>/tmp/pr-reply-<id>.txt. With --checkout, the PR, <repo_root>
and the push belong to that checkout of another repo.

Before pushing, every reply file must exist with its [COMMIT LINK] placeholder filled in, or nothing happens. If the
push fails, its output is printed and nothing is posted: a reply's commit link would not resolve. Otherwise each reply
is posted with pr-comments' post.py (which adds the AI attribution footer), and a JSON summary is printed:
  {"head": "<sha pushed>", "posted": [{"comment_id", "comment_type", "url"}], "failed": [{"comment_id", "error"}]}
Exits with status 1 if anything failed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from shell import run
from utils import COMMIT_LINK_PLACEHOLDER
from utils import count_commit_link_placeholders
from utils import enter_checkout

PUSH_TIMEOUT_SECONDS = 120
POST_TIMEOUT_SECONDS = 60
_POSTED_URL_RE = re.compile(r"^Posted: (?P<url>\S+)", re.MULTILINE)


def _fail(message: str) -> NoReturn:
    _ = sys.stderr.write(f"{message}\n")
    sys.exit(1)


def _repo_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], timeout=15)
    if result.returncode != 0:
        _fail(f"Not inside a git repository: {result.stderr.strip()}")
    return Path(result.stdout.strip())


def _reply_files(*, repo_root: Path, comment_ids: list[int]) -> dict[int, Path]:
    """Return each reply's file, failing before anything is pushed if one is missing or still has its placeholder."""
    problems: list[str] = []
    files: dict[int, Path] = {}
    for comment_id in comment_ids:
        path = repo_root / "tmp" / f"pr-reply-{comment_id}.txt"
        if not path.is_file():
            problems.append(f"{path} does not exist")
            continue
        if count_commit_link_placeholders(path.read_text(encoding="utf-8")) > 0:
            problems.append(
                f"{path} still has its {COMMIT_LINK_PLACEHOLDER} placeholder; run commit_link.py on it first"
            )
            continue
        files[comment_id] = path
    if problems:
        _fail("Nothing pushed or posted:\n- " + "\n- ".join(problems))
    return files


def _push_environment(*, checkout: Path | None) -> dict[str, str] | None:
    """Return the environment for `git push`: without the injected tokens when pushing another repo's checkout.

    In a codespace, git's credential helper answers with the injected GITHUB_TOKEN, which reaches only the codespace's
    own repository. Without the token, git falls through to the helper `gh auth login` set up, whose stored login
    reaches every repo the user can.
    """
    if checkout is None:
        return None
    env = dict(os.environ)
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        _ = env.pop(name, None)
    return env


def _push(*, checkout: Path | None) -> str:
    try:
        result = run(["git", "push"], timeout=PUSH_TIMEOUT_SECONDS, env=_push_environment(checkout=checkout))
    except subprocess.TimeoutExpired:
        _fail(f"git push did not finish within {PUSH_TIMEOUT_SECONDS}s, so nothing was posted. Check the remote.")
    if result.returncode != 0:
        _fail(f"git push failed, so nothing was posted:\n{result.stdout}{result.stderr}")
    head = run(["git", "rev-parse", "HEAD"], timeout=15)
    return head.stdout.strip()


def _post(*, pr: int, comment_id: int, comment_type: str, body_file: Path) -> dict[str, Any]:
    command = [
        str(Path(__file__).parent.parent / "pr-comments" / "post.py"),
        "--comment-id",
        str(comment_id),
        "--comment-type",
        comment_type,
        "--body-file",
        str(body_file),
        "--pr",
        str(pr),
    ]
    try:
        result = run(command, timeout=POST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        # the post may still have gone through, so this needs a look rather than a blind retry
        return {"comment_id": comment_id, "error": f"post.py did not finish within {POST_TIMEOUT_SECONDS}s"}
    if result.returncode != 0:
        return {"comment_id": comment_id, "error": (result.stderr or result.stdout).strip()}
    posted = _POSTED_URL_RE.search(result.stdout)
    if posted is None:
        return {"comment_id": comment_id, "error": f"post.py printed no URL: {result.stdout.strip()}"}
    return {"comment_id": comment_id, "comment_type": comment_type, "url": posted.group("url")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--pr", required=True, type=int)
    _ = parser.add_argument("--inline", nargs="+", type=int, default=[], help="root IDs of inline review threads")
    _ = parser.add_argument("--top-level", nargs="+", type=int, default=[], help="IDs of top-level PR comments")
    _ = parser.add_argument("--review", nargs="+", type=int, default=[], help="IDs of reviews whose body is answered")
    _ = parser.add_argument("--checkout", type=Path, default=None, help="a checkout of the PR's repo to push from")
    args = parser.parse_args()

    replies = (
        [(i, "pulls/comments") for i in args.inline]
        + [(i, "issues/comments") for i in args.top_level]
        + [(i, "pulls/reviews") for i in args.review]
    )
    if not replies:
        _fail("Give at least one --inline, --top-level or --review ID.")
    enter_checkout(args.checkout)
    files = _reply_files(repo_root=_repo_root(), comment_ids=[comment_id for comment_id, _ in replies])
    head = _push(checkout=args.checkout)

    posted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for comment_id, comment_type in replies:
        result = _post(pr=args.pr, comment_id=comment_id, comment_type=comment_type, body_file=files[comment_id])
        if "error" in result:
            failed.append(result)
        else:
            posted.append(result)
    _ = sys.stdout.write(json.dumps({"head": head, "posted": posted, "failed": failed}, indent=2) + "\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
