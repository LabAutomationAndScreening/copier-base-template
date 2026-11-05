#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Commit one comment's change and link its reply to that commit, for the address-pr-comments skill.

Usage:
  commit_for_comment.py --pr <number> --reply <comment id> --files <path> ... [--follower <comment id> ...]
                        [--bd <issue id>] [--checkout <path>] < commit-message

The commit message is read from stdin. Before anything is committed, the reply file
(<repo_root>/tmp/pr-reply-<id>.txt) of --reply and of each --follower must exist with its [COMMIT LINK]
placeholder. Then it stages exactly --files and commits them. With --checkout, the PR, <repo_root> and the commit
belong to that checkout of another repo, while bd stays with the current directory's repo; --files are still resolved
against the current directory, so give them as absolute paths. Pre-commit hooks run during the commit, and their output
is never discarded: if the commit fails it is printed and nothing else happens.

After the commit, it fills each reply file's placeholder with the new commit's link in the PR. With --bd it
appends the commit and the reply text to that issue's description, closes the issue and exports the bd database.

Exit status 1 always means nothing was committed, so running it again is safe. Once the commit exists the exit status
is 0, and anything that failed afterwards is listed under "errors" in the JSON it prints, to be fixed by hand rather
than by running this again:
  {"commit": "<sha>", "linked": ["<reply file>", ...], "bd": "<issue id>" | null, "errors": ["...", ...]}
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from shell import run
from utils import COMMIT_LINK_PLACEHOLDER
from utils import count_commit_link_placeholders
from utils import enter_checkout
from utils import fill_commit_link_placeholders
from utils import owner_repo_from_remote
from utils import pr_commit_link

COMMIT_TIMEOUT_SECONDS = 600
BD_EXPORT_PATH = Path(".claude/.beads/issues-dump.jsonl")


def _fail(message: str) -> NoReturn:
    _ = sys.stderr.write(f"{message}\n")
    sys.exit(1)


def _git_output(*args: str, cwd: Path) -> str:
    result = run(["git", *args], cwd=cwd)
    if result.returncode != 0:
        _fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _reply_files(*, repo_root: Path, comment_ids: list[int]) -> list[Path]:
    """Return the reply file of each comment the commit settles, checking them all before anything is committed.

    Each must exist, since its reply is approved before the commit, and must still hold a [COMMIT LINK] placeholder
    outside code to fill: one without has been linked already, by an earlier run of this commit. Every problem is
    reported at once, and nothing is committed while there is one.
    """
    problems: list[str] = []
    files: list[Path] = []
    for comment_id in comment_ids:
        path = repo_root / "tmp" / f"pr-reply-{comment_id}.txt"
        if not path.is_file():
            problems.append(f"{path} does not exist; write and approve the reply first")
            continue
        if count_commit_link_placeholders(path.read_text(encoding="utf-8")) == 0:
            problems.append(f"{path} has no {COMMIT_LINK_PLACEHOLDER} placeholder to fill outside code")
            continue
        files.append(path)
    if problems:
        _fail("Nothing committed:\n- " + "\n- ".join(problems))
    return files


def _commit(*, repo_root: Path, files: list[str], message: str) -> str:
    # git commit takes everything staged, so anything staged before --files would land in this comment's commit
    already_staged = _git_output("diff", "--cached", "--name-only", cwd=repo_root).splitlines()
    if already_staged:
        _fail(f"Nothing committed: unstage these first: {', '.join(already_staged)}")
    staged = run(["git", "add", "--", *files], cwd=repo_root)
    if staged.returncode != 0:
        _fail(f"Nothing committed: git add failed:\n{staged.stderr.strip()}")
    if run(["git", "diff", "--cached", "--quiet"], cwd=repo_root).returncode == 0:
        _fail("Nothing committed: --files has no changes to stage.")
    before = _git_output("rev-parse", "HEAD", cwd=repo_root)
    try:
        result = run(["git", "commit", "-F", "-"], cwd=repo_root, stdin=message, timeout=COMMIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        after = _git_output("rev-parse", "HEAD", cwd=repo_root)
        if after != before:
            # a post-commit hook ran past the timeout, but git had already made the commit
            return after
        reset = run(["git", "reset", "-q", "--", *files], cwd=repo_root)
        message = f"Nothing committed: git commit did not finish within {COMMIT_TIMEOUT_SECONDS}s."
        if reset.returncode != 0:
            # git killed mid-commit leaves .git/index.lock behind, which also stops the reset, so --files stay staged
            message += (
                f"\n--files are still staged, since git reset failed:\n{reset.stderr.strip()}\n"
                "If no git process is running, remove .git/index.lock, then unstage them before running this again."
            )
        _fail(message)
    after = _git_output("rev-parse", "HEAD", cwd=repo_root)
    if result.returncode != 0:
        # git leaves --files staged when a hook fails; unstaged, they pass the guard above when this is run again
        _ = run(["git", "reset", "-q", "--", *files], cwd=repo_root)
        _fail(f"Nothing committed: git commit failed (a pre-commit hook, most likely):\n{result.stdout}{result.stderr}")
    if after == before:
        _ = run(["git", "reset", "-q", "--", *files], cwd=repo_root)
        _fail(f"Nothing committed: HEAD did not move.\n{result.stdout}{result.stderr}")
    return after


def _link(*, link: str, reply_files: list[Path]) -> tuple[list[str], list[str]]:
    linked: list[str] = []
    errors: list[str] = []
    for path in reply_files:
        try:
            _ = path.write_text(
                fill_commit_link_placeholders(path.read_text(encoding="utf-8"), link=link), encoding="utf-8"
            )
        except OSError as e:
            errors.append(f"linking {path}: {e}")
        else:
            linked.append(str(path))
    return linked, errors


def _shown_description(*, shown: object, issue_id: str) -> tuple[str, list[str]]:
    unknown_shape = f"bd show {issue_id} printed JSON of an unknown shape; record the commit on it and close it by hand"
    # BD_JSON_ENVELOPE=1 wraps the usual array as {"schema_version": ..., "data": [...]}
    if isinstance(shown, dict):
        shown = shown.get("data")
    if not isinstance(shown, list):
        return "", [unknown_shape]
    if not shown:
        return "", [f"bd show {issue_id} returned no issue; record the commit on it and close it by hand"]
    issue = shown[0]
    if not isinstance(issue, dict):
        return "", [unknown_shape]
    return issue.get("description") or "", []


def _issue_description(*, bd_root: Path, issue_id: str) -> tuple[str, list[str]]:
    try:
        shown = run(["bd", "show", issue_id, "--json"], cwd=bd_root)
    except subprocess.TimeoutExpired:
        return "", [f"bd show {issue_id} timed out; record the commit on the issue and close it by hand"]
    except OSError as e:
        return "", [f"bd could not run ({e}); record the commit on {issue_id} and close it by hand"]
    if shown.returncode != 0:
        return "", [f"bd show {issue_id}: {shown.stderr.strip()}"]
    try:
        parsed = json.loads(shown.stdout)
    except json.JSONDecodeError as e:
        return "", [f"bd show {issue_id} printed no JSON ({e}); record the commit on the issue and close it by hand"]
    return _shown_description(shown=parsed, issue_id=issue_id)


def _close_bd_issue(*, bd_root: Path, issue_id: str, commit: str, reply_file: Path) -> list[str]:
    # the commit already exists, so every failure from here on is reported under errors, never raised: exit 1 has to
    # keep meaning nothing was committed
    description, errors = _issue_description(bd_root=bd_root, issue_id=issue_id)
    if errors:
        return errors
    try:
        reply = reply_file.read_text(encoding="utf-8").strip()
    except OSError as e:
        return [f"reading {reply_file}: {e}; record the commit on {issue_id} and close it by hand"]
    updated = f"{description}\n\ncommit: {commit}\nreply: {reply}".strip()
    # each step needs the one before it: an issue closed without its commit and reply recorded would look settled
    steps: list[tuple[list[str], str | None]] = [
        (["bd", "update", issue_id, "--stdin", "--json"], updated),
        (["bd", "close", issue_id, "--reason", "Addressed in PR review", "--json"], None),
        (["bd", "export", "-o", str(BD_EXPORT_PATH)], None),
    ]
    for command, stdin in steps:
        try:
            result = run(command, cwd=bd_root, stdin=stdin)
        except subprocess.TimeoutExpired:
            return [f"{' '.join(command[:3])} timed out; finish this step and the ones after it by hand"]
        except OSError as e:
            return [f"{' '.join(command[:3])} could not run ({e}); finish this step and the ones after it by hand"]
        if result.returncode != 0:
            return [f"{' '.join(command[:3])}: {result.stderr.strip()}"]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--pr", required=True, type=int)
    _ = parser.add_argument("--reply", required=True, type=int, help="the comment this commit addresses")
    _ = parser.add_argument("--follower", nargs="+", type=int, default=[], help="comments this commit also settles")
    _ = parser.add_argument("--files", nargs="+", required=True, help="exactly the files to commit")
    _ = parser.add_argument("--bd", default=None, help="the bd issue to record the commit on and close")
    _ = parser.add_argument("--checkout", type=Path, default=None, help="a checkout of the PR's repo to commit in")
    args = parser.parse_args()

    message = sys.stdin.read()
    if not message.strip():
        _fail("Nothing committed: the commit message (stdin) is empty.")
    bd_root = Path(_git_output("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    # resolved against the current directory, since a session often works from a subdirectory such as backend/
    files = [str(Path(path).resolve()) for path in args.files]
    enter_checkout(args.checkout)
    repo_root = Path(_git_output("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    reply_files = _reply_files(repo_root=repo_root, comment_ids=[args.reply, *args.follower])
    # read before committing, since a remote it can't parse exits 1, which has to mean nothing was committed
    owner, repo = owner_repo_from_remote()
    commit = _commit(repo_root=repo_root, files=files, message=message)

    link = pr_commit_link(owner=owner, repo=repo, pr=args.pr, commit=commit)
    linked, errors = _link(link=link, reply_files=reply_files)
    if args.bd is not None:
        errors += _close_bd_issue(bd_root=bd_root, issue_id=args.bd, commit=commit, reply_file=reply_files[0])
    _ = sys.stdout.write(
        json.dumps({"commit": commit, "linked": linked, "bd": args.bd, "errors": errors}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
