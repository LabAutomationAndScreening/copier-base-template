# /// script
# requires-python = ">=3.12"
# ///
"""Wait for CI on a GitHub PR, or with no PR on a pushed commit, then print exactly one result line.

Meant to run as a background command, so the caller gets one notification when CI settles instead of polling it.
Result lines and exit codes, in PR mode unless marked otherwise:

- MERGED (0)
- CHECKS_PASSED (0): every required check passed and auto-merge is off, so nothing more happens without a person
- CI_PASSED_MERGE_BLOCKED: <check>: <its description> (0): every GitHub Actions check finished without a failure, but a
  required commit status was posted as pending, which holds the merge on purpose (such as a copier template not yet
  on a release tag). Exit 0 means CI passed, not that the PR can merge. Only a status that GitHub Actions posted
  counts as a hold: once every Actions run has finished, one it left pending can only be deliberate, whereas a pending
  status from anyone else (Jenkins, CircleCI, an App) is CI still running, so the wait goes on.
- CI_PASSED_MERGE_BLOCKED: reviewDecision=<decision> (0): with auto-merge on, CI passed but the merge waits on a review
  (REVIEW_REQUIRED or CHANGES_REQUESTED), so it won't happen without a person
- CI_PASSED_MERGE_BLOCKED: mergeStateStatus=<status> (0): with auto-merge on, CI passed but the PR still hasn't merged
  a minute later, so something else holds it (a ruleset, unresolved conversations, a deployment gate)
- CLOSED (1)
- CHECKS_FAILED: <names> (1): a GitHub Actions job or a required check failed or was cancelled; stops at the first
  failure rather than waiting for the remaining checks. Other checks, such as an AI reviewer's, are ignored when they
  fail: they aren't CI, and as they aren't required they can't block the merge either.
- AUTO_MERGE_DISABLED: mergeStateStatus=<status> (1): auto-merge was on but got switched off, reported as soon as it
  happens. The status tells the cause apart: DIRTY means GitHub turned it off over a merge conflict, while CLEAN or
  BLOCKED mean a person turned it off. In a repo with a merge queue, auto-merge also goes off when it puts the PR in
  the queue, so a queued PR is still waited on (the timeout then says "in merge queue"), and only a PR that is
  neither auto-merging nor queued, such as one the queue dropped after its merge_group CI failed, is reported.
- GH_UNREACHABLE: <last error> (1): several polls in a row failed or timed out
- GH_NOT_FOUND: <gh's message> (1): GitHub says the PR, repo or commit doesn't exist or isn't visible with either set of
  credentials, which no retry fixes, so it is reported at once
- TIMED_OUT after <n> minutes (1): the deadline passed with the PR still unsettled, such as checks stuck pending on a
  runner; when the PR's head never reached the awaited commit, the line names both
- LOCAL_HEAD_NOT_PUSHED: <sha> (1): no --sha was given, the local HEAD would be awaited (commit mode, or the PR is the
  checked-out branch), and it isn't pushed
- UNKNOWN_COMMIT: <sha> (1): GitHub has no commit matching --sha in the repo
- NO_RUNS: <sha> was never the tip of a push, so CI never ran on it (1): the PR's head moved past the awaited commit
  and it still has no workflow runs a couple of polls later; GitHub only runs workflows on the commit a push ends at

Commit mode (no PR given) waits on every GitHub Actions workflow run for one commit, whatever event triggered it:
--sha (expanded through GitHub when abbreviated, since the `gh run list` filter only matches a full SHA), or else the
pushed local HEAD. Its result lines:

- CHECKS_PASSED (0): at least one run exists and every run completed without a failed job. When the commit is the head
  of an open PR, a pull_request run must also exist: a push to a PR's branch triggers both a push run and a
  pull_request run, and CI may skip the push run's jobs as a duplicate, so the push run can finish before the
  pull_request run that does the work has even been created.
- CHECKS_FAILED: <job names> (1): a job concluded failure, cancelled, timed_out or startup_failure; reported as soon as
  the job finishes, without waiting for the rest of its run. A run that never ran its jobs, because it awaits approval
  (action_required) or GitHub gave up on it (stale), is listed as `<workflow> (<conclusion>)`.
- TIMED_OUT after <n> minutes (1): as in PR mode; when no run ever appeared, such as for a commit whose push triggers no
  workflow, the line says so

Success is judged by the PR's required checks only, because a repo's required gate (such as a summary job that runs
after every other job) can't pass early, whereas the set of all checks grows as jobs start, so it can look complete
between one job finishing and the next starting. A repo with no required checks therefore never reaches
CHECKS_PASSED and times out. Failures are still caught from every check, so they are reported as soon as they happen.
Required checks alone can still pass early, when a required status is posted at the start of CI or when the required
checks are individual jobs that don't exist yet, so CHECKS_PASSED and CI_PASSED_MERGE_BLOCKED also wait until every
GitHub Actions workflow run for the head commit has completed: a run completes only after all of its jobs. At least
one of them must be a pull_request (or pull_request_target) run, since a push run may be all CI has created so far and
can count its skipped duplicate jobs as passing. A repo with no Actions workflows (only third-party CI), or whose
workflows never run on pull requests, therefore never reaches either and times out.

Right after a push, GitHub can still report the previous commit as the PR's head, with that commit's finished checks.
So while the PR is open, checks count only once its head is the awaited commit: --sha when given; otherwise, when the
PR's branch is the one checked out here (and --repo isn't given), the local HEAD, which must already be pushed;
otherwise whatever head GitHub shows. That choice is settled once, on the first poll that reads the PR, so a commit
pushed while waiting doesn't change what is awaited.

If the PR's head moves past the awaited commit instead (a later push, a commit CI itself pushes, "Update branch", a
force-push), that commit's own CI still finishes, so the wait switches to commit mode's rules for it, and every line
then ends with "(PR head has since moved to <sha>)". A pull_request run is required unless every push run for the
commit started before the PR was opened: until then no PR existed for CI to treat the push run as a duplicate of, so
the push run really ran the jobs.
The PR's merge state, auto-merge and holds belong to the new head, so they no longer count. A head GitHub shows as
behind the awaited commit means the push isn't registered yet, so the wait goes on.

A failed or timed-out gh call only costs that poll, so a passing network blip or GitHub 5xx doesn't end the wait.

A cancelled job or check counts as a failure in both modes, including one that a `concurrency: cancel-in-progress`
group cancels in favour of a duplicate run of the same commit, so CI that cancels duplicates that way would report
CHECKS_FAILED while the duplicate passes.

gh calls prefer the login `gh auth login` stored over GITHUB_TOKEN/GH_TOKEN, because the GITHUB_TOKEN a codespace
injects reaches only the codespace's own repository. The environment's token is used only when the stored login can't
read the PR or the commit's runs (none stored, or one without access to the repo), and that choice is made once per run, so a later call's
normal non-zero exit, such as `gh pr checks` reporting pending checks, never switches credentials.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

POLL_SECONDS = 30
GH_TIMEOUT_SECONDS = 30
# The last sleep ends right at the deadline, so without a floor the final poll's calls would time out at once and the
# script would never take the last look that could catch a merge landing just before the deadline.
GH_MIN_TIMEOUT_SECONDS = 5
MAX_CONSECUTIVE_FAILED_POLLS = 5
DEFAULT_DEADLINE_MINUTES = 20
# GitHub creates a push's workflow runs within seconds, so a superseded commit still without any after this many polls
# was never the tip of a push and never will have any
NO_RUNS_GRACE_POLLS = 2
# auto-merge acts within seconds of the last required check passing, so a PR whose CI has passed and that is still
# open after this many polls is held by something else
MERGE_GRACE_POLLS = 2
FULL_SHA_LENGTH = 40
# action_required (awaiting approval) and stale (abandoned by GitHub) mean the run's jobs never ran, so it can't pass
_FAILED_CONCLUSIONS = frozenset({"failure", "cancelled", "timed_out", "startup_failure", "action_required", "stale"})
_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
# the creator GitHub records on a commit status that a workflow posts with its GITHUB_TOKEN
_GITHUB_ACTIONS_LOGIN = "github-actions[bot]"
# also matches the URL `gh pr view` reports, whatever the PR was given as, which names its base repo
_PR_URL_REPO = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/pull/\d+")


class GhCallFailedError(Exception):
    pass


class GhNotFoundError(GhCallFailedError):
    pass


# what gh prints when the PR, repo or commit asked for doesn't exist or the credentials can't see it: GraphQL lookups
# (pr view/checks) and the REST calls (run list, api) word it differently
_NOT_FOUND_MARKERS = ("Could not resolve to a", "no pull requests found", "HTTP 404")


def _gh_failure(*, stderr: str) -> GhCallFailedError:
    message = stderr.strip()
    for marker in _NOT_FOUND_MARKERS:
        if marker in message:
            return GhNotFoundError(message)
    return GhCallFailedError(message)


class LocalHeadNotPushedError(Exception):
    def __init__(self, *, sha: str) -> None:
        super().__init__(sha)
        self.sha = sha


class UnknownCommitError(Exception):
    def __init__(self, *, sha: str) -> None:
        super().__init__(sha)
        self.sha = sha


@dataclass(frozen=True)
class _PrState:
    state: str
    auto_merge_on: bool
    head_sha: str
    head_branch: str
    merge_state_status: str
    # empty when the repo requires no review
    review_decision: str
    created_at: str
    number: int
    url: str


@dataclass(frozen=True)
class _LocalHead:
    branch: str
    sha: str


@dataclass(frozen=True)
class _Check:
    name: str
    bucket: str
    # empty for anything that isn't a GitHub Actions job, such as a commit status or a third-party app's check
    workflow: str
    description: str


@dataclass(frozen=True)
class _Run:
    run_id: int
    status: str
    conclusion: str
    workflow_name: str
    event: str
    created_at: str


@dataclass(frozen=True)
class _Job:
    name: str
    status: str
    conclusion: str


@dataclass(frozen=True)
class _PrSnapshot:
    pr: _PrState
    checks: list[_Check]
    required_checks: list[_Check]


def _env_without_tokens() -> dict[str, str]:
    env = dict(os.environ)
    for name in _TOKEN_NAMES:
        _ = env.pop(name, None)
    return env


def _tokens_in_env() -> bool:
    for name in _TOKEN_NAMES:
        if name in os.environ:
            return True
    return False


def _gh(*args: str, env: dict[str, str], deadline: float) -> subprocess.CompletedProcess[str]:
    cmd = ["gh", *args]
    timeout_seconds = max(GH_MIN_TIMEOUT_SECONDS, min(GH_TIMEOUT_SECONDS, deadline - time.monotonic()))
    try:
        return subprocess.run(  # noqa: S603 # gh is the only executable and every value is a separate argument
            cmd, capture_output=True, text=True, check=False, env=env, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as e:
        raise GhCallFailedError(f"`{' '.join(cmd)}` timed out after {timeout_seconds:.0f}s") from e


def _git(*args: str) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 # git is the only executable and every value is a separate argument
            ["git", *args],  # noqa: S607 # found on PATH, the same way gh is
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _local_head() -> _LocalHead | None:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return None
    sha = _git("rev-parse", "HEAD")
    if sha is None:
        return None
    return _LocalHead(branch=branch, sha=sha)


# Both checks read remote-tracking refs, which `git push` moves at once (with or without -u, whatever the branch's
# upstream) and before GitHub has registered the push, so they hold in the very window the awaited-commit check exists
# for. The branch's upstream would not do: one created from origin/main tracks origin/main, and one may have none.


def _git_lists_any(*args: str) -> bool:
    listed = _git(*args)
    if listed is None:
        return False
    if listed == "":
        return False
    return True


def _pushed_to_branch(*, sha: str, branch: str) -> bool:
    return _git_lists_any("for-each-ref", "--points-at", sha, "--format=%(refname)", f"refs/remotes/*/{branch}")


def _pushed_anywhere(*, sha: str) -> bool:
    return _git_lists_any("for-each-ref", "--contains", sha, "--format=%(refname)", "refs/remotes")


def _repo_args(*, repo: str | None) -> list[str]:
    if repo is None:
        return []
    return ["--repo", repo]


def _unexpected_output(*, command: str, stdout: str) -> GhCallFailedError:
    return GhCallFailedError(f"`{command}` returned unexpected output: {stdout[:200]!r}")


def _parse_json(*, command: str, stdout: str) -> object:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise _unexpected_output(command=command, stdout=stdout) from e


def _string_field(*, obj: dict[object, object], key: str, error: GhCallFailedError) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise error
    return value


def _int_field(*, obj: dict[object, object], key: str, error: GhCallFailedError) -> int:
    value = obj.get(key)
    if not isinstance(value, int):
        raise error
    return value


def _json_objects(*, command: str, stdout: str) -> list[dict[object, object]]:
    error = _unexpected_output(command=command, stdout=stdout)
    parsed = _parse_json(command=command, stdout=stdout)
    if not isinstance(parsed, list):
        raise error
    objects: list[dict[object, object]] = []
    item: object  # isinstance only narrows parsed to a list of unknowns; object is true of any JSON value
    for item in parsed:
        if not isinstance(item, dict):
            raise error
        objects.append(item)
    return objects


def _pr_view(*, pr: str, repo: str | None, env: dict[str, str], deadline: float) -> _PrState:
    completed = _gh(
        "pr",
        "view",
        pr,
        *_repo_args(repo=repo),
        "--json",
        "state,autoMergeRequest,headRefOid,headRefName,mergeStateStatus,reviewDecision,createdAt,number,url",
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    command = "gh pr view"
    error = _unexpected_output(command=command, stdout=completed.stdout)
    parsed = _parse_json(command=command, stdout=completed.stdout)
    if not isinstance(parsed, dict):
        raise error
    if "autoMergeRequest" not in parsed:
        raise error
    return _PrState(
        state=_string_field(obj=parsed, key="state", error=error),
        auto_merge_on=parsed["autoMergeRequest"] is not None,
        head_sha=_string_field(obj=parsed, key="headRefOid", error=error),
        head_branch=_string_field(obj=parsed, key="headRefName", error=error),
        merge_state_status=_string_field(obj=parsed, key="mergeStateStatus", error=error),
        review_decision=_string_field(obj=parsed, key="reviewDecision", error=error),
        created_at=_string_field(obj=parsed, key="createdAt", error=error),
        number=_int_field(obj=parsed, key="number", error=error),
        url=_string_field(obj=parsed, key="url", error=error),
    )


def _select_gh_env[T](*, probe: Callable[[dict[str, str]], T]) -> tuple[dict[str, str], T]:
    stored_login_env = _env_without_tokens()
    try:
        probed = probe(stored_login_env)
    except GhCallFailedError:
        if not _tokens_in_env():
            raise
    else:
        return stored_login_env, probed
    token_env = dict(os.environ)
    return token_env, probe(token_env)


def _required_args(*, required: bool) -> list[str]:
    if required:
        return ["--required"]
    return []


def _checks(*, pr: str, repo: str | None, env: dict[str, str], deadline: float, required: bool) -> list[_Check]:
    completed = _gh(
        "pr",
        "checks",
        pr,
        *_repo_args(repo=repo),
        *_required_args(required=required),
        "--json",
        "name,bucket,workflow,description",
        env=env,
        deadline=deadline,
    )
    # gh exits non-zero while checks are pending or failing, so JSON on stdout, not the exit code, says it worked.
    if completed.stdout.strip() == "":
        # Until a check is reported (right after a push, or until a required status is posted), gh reports an error.
        if "no checks reported" in completed.stderr:
            return []
        if "no required checks reported" in completed.stderr:
            return []
        raise _gh_failure(stderr=completed.stderr)
    command = "gh pr checks"
    error = _unexpected_output(command=command, stdout=completed.stdout)
    return [
        _Check(
            name=_string_field(obj=item, key="name", error=error),
            bucket=_string_field(obj=item, key="bucket", error=error),
            workflow=_string_field(obj=item, key="workflow", error=error),
            description=_string_field(obj=item, key="description", error=error),
        )
        for item in _json_objects(command=command, stdout=completed.stdout)
    ]


def _snapshot(*, pr_state: _PrState, pr: str, repo: str | None, env: dict[str, str], deadline: float) -> _PrSnapshot:
    return _PrSnapshot(
        pr=pr_state,
        checks=_checks(pr=pr, repo=repo, env=env, deadline=deadline, required=False),
        required_checks=_checks(pr=pr, repo=repo, env=env, deadline=deadline, required=True),
    )


def _is_failure(*, check: _Check) -> bool:
    if check.bucket == "fail":
        return True
    if check.bucket == "cancel":
        return True
    return False


def _failed_check_names(*, checks: list[_Check], required_checks: list[_Check]) -> list[str]:
    required_names = {check.name for check in required_checks}
    names: list[str] = []
    for check in checks:
        if not _is_failure(check=check):
            continue
        if check.workflow != "":
            names.append(check.name)
        elif check.name in required_names:
            names.append(check.name)
    return names


def _any_pending(*, checks: list[_Check]) -> bool:
    for check in checks:
        if check.bucket == "pending":
            return True
    return False


def _merge_blocking_status(*, checks: list[_Check], required_checks: list[_Check]) -> _Check | None:
    for check in checks:
        if check.bucket != "pending":
            continue
        if check.workflow != "":
            return None
    for check in required_checks:
        if check.bucket != "pending":
            continue
        if check.workflow == "":
            return check
    return None


def _open_pr_result(
    *, snapshot: _PrSnapshot, auto_merge_dropped: bool, queue_detail: str | None, held_status: _Check | None
) -> tuple[str, int] | None:
    failed = _failed_check_names(checks=snapshot.checks, required_checks=snapshot.required_checks)
    if len(failed) > 0:
        return f"CHECKS_FAILED: {', '.join(failed)}", 1
    if auto_merge_dropped:
        # still on its way to merging, just through the queue instead of auto-merge
        if queue_detail is not None:
            return None
        # GitHub computes the merge state lazily, so the first read after a change can be UNKNOWN; the next poll
        # has the real cause.
        if snapshot.pr.merge_state_status == "UNKNOWN":
            return None
        return f"AUTO_MERGE_DISABLED: mergeStateStatus={snapshot.pr.merge_state_status}", 1
    # Reported even with auto-merge on, since the merge it would wait for can't happen while the status holds it.
    if held_status is not None:
        return f"CI_PASSED_MERGE_BLOCKED: {held_status.name}: {held_status.description}", 0
    return _passed_result(snapshot=snapshot)


def _passed_result(*, snapshot: _PrSnapshot) -> tuple[str, int] | None:
    if len(snapshot.required_checks) == 0:
        return None
    if _any_pending(checks=snapshot.required_checks):
        return None
    if not snapshot.pr.auto_merge_on:
        return "CHECKS_PASSED", 0
    # With auto-merge on, the merge itself is the outcome, unless something besides CI holds it; a review is the usual
    # hold, and the one GitHub reports directly.
    if _review_blocks_merge(review_decision=snapshot.pr.review_decision):
        return f"CI_PASSED_MERGE_BLOCKED: reviewDecision={snapshot.pr.review_decision}", 0
    return None


def _review_blocks_merge(*, review_decision: str) -> bool:
    if review_decision == "REVIEW_REQUIRED":
        return True
    if review_decision == "CHANGES_REQUESTED":
        return True
    return False


@dataclass(frozen=True)
class _Target:
    pr: str
    repo: str | None
    sha: str | None
    local_head: _LocalHead | None
    deadline: float


@dataclass(frozen=True)
class _Awaited:
    # the full SHA the PR's head must reach before its checks count; None accepts whatever head GitHub shows
    sha: str | None


@dataclass(frozen=True)
class _RepoAccess:
    repo: str | None
    gh_env: dict[str, str]
    deadline: float


@dataclass(frozen=True)
class _Superseded:
    gh_env: dict[str, str]
    awaited_sha: str
    head_sha: str
    pr_created_at: str


@dataclass
class _PollState:
    gh_env: dict[str, str] | None = None
    # PR mode's awaited commit, settled on the first poll that reads the PR
    awaited: _Awaited | None = None
    # commit mode's awaited commit, expanded to the full SHA on the first successful poll
    commit_sha: str | None = None
    saw_auto_merge: bool = False
    # the last PR head compared with the awaited commit, so each head costs one compare call
    compared_head: str | None = None
    superseded: _Superseded | None = None
    # polls since the switch that found no workflow runs at all for the superseded commit
    empty_run_polls: int = 0
    # polls with auto-merge on and CI fully passed that found the PR still unmerged
    merge_wait_polls: int = 0
    # what the TIMED_OUT line adds about why nothing settled, as of the latest successful poll
    timeout_detail: str | None = None


def _awaited_local_head(*, sha: str | None, repo: str | None) -> _LocalHead | None:
    if sha is not None:
        return None
    if repo is not None:
        return None
    return _local_head()


def _settle_awaited(*, target: _Target, pr_head_branch: str, env: dict[str, str]) -> _Awaited:
    if target.sha is not None:
        return _Awaited(sha=_resolve_commit(sha=target.sha, repo=target.repo, env=env, deadline=target.deadline))
    if target.local_head is None:
        return _Awaited(sha=None)
    if target.local_head.branch != pr_head_branch:
        return _Awaited(sha=None)
    if not _pushed_to_branch(sha=target.local_head.sha, branch=pr_head_branch):
        raise LocalHeadNotPushedError(sha=target.local_head.sha)
    return _Awaited(sha=target.local_head.sha)


def _read_pr(*, target: _Target, state: _PollState) -> tuple[dict[str, str], _PrState, str | None]:
    if state.gh_env is None:
        state.gh_env, pr_state = _select_gh_env(
            probe=lambda env: _pr_view(pr=target.pr, repo=target.repo, env=env, deadline=target.deadline)
        )
    else:
        pr_state = _pr_view(pr=target.pr, repo=target.repo, env=state.gh_env, deadline=target.deadline)
    if state.awaited is None:
        state.awaited = _settle_awaited(target=target, pr_head_branch=pr_state.head_branch, env=state.gh_env)
    return state.gh_env, pr_state, state.awaited.sha


def _compare_status(*, base: str, head: str, repo: str | None, env: dict[str, str], deadline: float) -> str:
    completed = _gh(
        "api",
        f"repos/{_api_repo_path(repo=repo)}/compare/{base}...{head}",
        "--jq",
        ".status",
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    return completed.stdout.strip()


def _supersession(
    *, pr_state: _PrState, expected_sha: str | None, target: _Target, env: dict[str, str], state: _PollState
) -> _Superseded | None:
    if expected_sha is None:
        return None
    if pr_state.head_sha == expected_sha:
        return None
    if state.compared_head == pr_state.head_sha:
        return None
    status = _compare_status(
        base=expected_sha, head=pr_state.head_sha, repo=target.repo, env=env, deadline=target.deadline
    )
    state.compared_head = pr_state.head_sha
    # ahead: the head was built on the awaited commit; diverged: a force-push replaced it. Behind means GitHub hasn't
    # registered the push of the awaited commit yet.
    if status == "ahead":
        return _Superseded(
            gh_env=env, awaited_sha=expected_sha, head_sha=pr_state.head_sha, pr_created_at=pr_state.created_at
        )
    if status == "diverged":
        return _Superseded(
            gh_env=env, awaited_sha=expected_sha, head_sha=pr_state.head_sha, pr_created_at=pr_state.created_at
        )
    return None


def _superseded_result(*, target: _Target, superseded: _Superseded, state: _PollState) -> tuple[str, int] | None:
    result = _commit_result(
        commit_sha=superseded.awaited_sha,
        access=_RepoAccess(repo=target.repo, gh_env=superseded.gh_env, deadline=target.deadline),
        state=state,
        pr_created_at=superseded.pr_created_at,
    )
    suffix = f" (PR head has since moved to {superseded.head_sha})"
    if state.timeout_detail is not None:
        state.timeout_detail += suffix
    if result is None:
        return None
    line, exit_code = result
    return f"{line}{suffix}", exit_code


def _pr_poll(*, target: _Target, state: _PollState) -> tuple[str, int] | None:
    if state.superseded is not None:
        return _superseded_result(target=target, superseded=state.superseded, state=state)
    gh_env, pr_state, expected_sha = _read_pr(target=target, state=state)
    saw_auto_merge = state.saw_auto_merge
    if pr_state.auto_merge_on:
        state.saw_auto_merge = True
    superseded = _supersession(pr_state=pr_state, expected_sha=expected_sha, target=target, env=gh_env, state=state)
    if superseded is not None:
        state.superseded = superseded
        return _superseded_result(target=target, superseded=superseded, state=state)
    # Decided from `gh pr view` alone, so these polls skip both `gh pr checks` calls.
    if pr_state.state == "MERGED":
        return "MERGED", 0
    if pr_state.state == "CLOSED":
        return "CLOSED", 1
    if expected_sha is not None:
        if pr_state.head_sha != expected_sha:
            state.timeout_detail = f"PR head is {pr_state.head_sha} but expected {expected_sha}"
            return None
    return _head_poll(target=target, state=state, gh_env=gh_env, pr_state=pr_state, saw_auto_merge=saw_auto_merge)


def _head_poll(
    *, target: _Target, state: _PollState, gh_env: dict[str, str], pr_state: _PrState, saw_auto_merge: bool
) -> tuple[str, int] | None:
    snapshot = _snapshot(pr_state=pr_state, pr=target.pr, repo=target.repo, env=gh_env, deadline=target.deadline)
    held_status, hold_detail = _confirmed_hold(
        snapshot=snapshot, repo=target.repo, env=gh_env, deadline=target.deadline
    )
    auto_merge_dropped = False
    queue_detail: str | None = None
    if saw_auto_merge:
        if not pr_state.auto_merge_on:
            auto_merge_dropped = True
            queue_detail = _merge_queue_detail(pr_state=pr_state, env=gh_env, deadline=target.deadline)
    result = _open_pr_result(
        snapshot=snapshot, auto_merge_dropped=auto_merge_dropped, queue_detail=queue_detail, held_status=held_status
    )
    runs_detail: str | None = None
    if result is None:
        grace_result, runs_detail = _merge_grace(snapshot=snapshot, target=target, gh_env=gh_env, state=state)
        if grace_result is not None:
            return grace_result
    else:
        _, exit_code = result
        # exit 0 on an open PR is a success line, which must also wait for every workflow run; fetched only here, so
        # polls while checks are still pending cost no extra call
        if exit_code != 0:
            return result
        runs_detail = _pr_runs_detail(
            commit_sha=pr_state.head_sha, repo=target.repo, env=gh_env, deadline=target.deadline
        )
        if runs_detail is None:
            return result
    state.timeout_detail = _pr_timeout_detail(
        snapshot=snapshot, runs_detail=runs_detail, hold_detail=hold_detail, queue_detail=queue_detail
    )
    return None


def _awaiting_merge(*, snapshot: _PrSnapshot) -> bool:
    if not snapshot.pr.auto_merge_on:
        return False
    if len(snapshot.required_checks) == 0:
        return False
    if _any_pending(checks=snapshot.required_checks):
        return False
    return True


def _merge_grace(
    *, snapshot: _PrSnapshot, target: _Target, gh_env: dict[str, str], state: _PollState
) -> tuple[tuple[str, int] | None, str | None]:
    if not _awaiting_merge(snapshot=snapshot):
        return None, None
    runs_detail = _pr_runs_detail(
        commit_sha=snapshot.pr.head_sha, repo=target.repo, env=gh_env, deadline=target.deadline
    )
    if runs_detail is not None:
        return None, runs_detail
    state.merge_wait_polls += 1
    if state.merge_wait_polls < MERGE_GRACE_POLLS:
        return None, None
    return (f"CI_PASSED_MERGE_BLOCKED: mergeStateStatus={snapshot.pr.merge_state_status}", 0), None


_MERGE_QUEUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) { isInMergeQueue mergeQueueEntry { position state } }
  }
}
"""


def _merge_queue_detail(*, pr_state: _PrState, env: dict[str, str], deadline: float) -> str | None:
    # `gh pr view --json` has no merge-queue field, so this asks GraphQL directly
    match = _PR_URL_REPO.match(pr_state.url)
    if match is None:
        raise _unexpected_output(command="gh pr view", stdout=pr_state.url)
    owner, name = match.group("repo").split("/")
    completed = _gh(
        "api",
        "graphql",
        "-f",
        f"query={_MERGE_QUEUE_QUERY}",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={pr_state.number}",
        "--jq",
        ".data.repository.pullRequest"
        ' | if .isInMergeQueue then "in merge queue (position \\(.mergeQueueEntry.position), \\(.mergeQueueEntry.state))"'
        ' else "" end',
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    detail = completed.stdout.strip()
    if detail == "":
        return None
    return detail


def _status_creator(*, sha: str, context: str, repo: str | None, env: dict[str, str], deadline: float) -> str:
    # GitHub lists a commit's statuses newest first, so the first one with this context is the one in effect;
    # json.dumps quotes the context as a jq string literal
    completed = _gh(
        "api",
        f"repos/{_api_repo_path(repo=repo)}/commits/{sha}/statuses?per_page=100",
        "--jq",
        f'[.[] | select(.context == {json.dumps(context)})][0].creator.login // ""',
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    return completed.stdout.strip()


def _confirmed_hold(
    *, snapshot: _PrSnapshot, repo: str | None, env: dict[str, str], deadline: float
) -> tuple[_Check | None, str | None]:
    candidate = _merge_blocking_status(checks=snapshot.checks, required_checks=snapshot.required_checks)
    if candidate is None:
        return None, None
    creator = _status_creator(sha=snapshot.pr.head_sha, context=candidate.name, repo=repo, env=env, deadline=deadline)
    if creator == _GITHUB_ACTIONS_LOGIN:
        return candidate, None
    return None, f"required status {candidate.name} from {creator} still pending"


def _pr_timeout_detail(
    *, snapshot: _PrSnapshot, runs_detail: str | None, hold_detail: str | None, queue_detail: str | None
) -> str | None:
    if queue_detail is not None:
        return queue_detail
    if runs_detail is not None:
        return runs_detail
    if hold_detail is not None:
        return hold_detail
    # GitHub's view of the merge, which may only reflect checks still pending, but names other holds when there are any
    if snapshot.pr.auto_merge_on:
        return f"auto-merge on; mergeStateStatus={snapshot.pr.merge_state_status}, reviewDecision={snapshot.pr.review_decision}"
    return None


def _unfinished_runs_detail(*, runs: list[_Run], commit_sha: str) -> str | None:
    if len(runs) == 0:
        return f"no workflow runs for {commit_sha}"
    for run in runs:
        if run.status != "completed":
            return f"workflow runs for {commit_sha} still in progress"
    return None


def _pr_runs_detail(*, commit_sha: str, repo: str | None, env: dict[str, str], deadline: float) -> str | None:
    runs = _runs(commit_sha=commit_sha, repo=repo, env=env, deadline=deadline)
    unfinished = _unfinished_runs_detail(runs=runs, commit_sha=commit_sha)
    if unfinished is not None:
        return unfinished
    if not _any_pull_request_run(runs=runs):
        return f"no pull_request run for {commit_sha} yet"
    return None


def _commit_to_await(*, sha: str | None) -> str:
    if sha is not None:
        return sha
    local_head = _local_head()
    if local_head is None:
        raise LocalHeadNotPushedError(sha="HEAD")
    if not _pushed_anywhere(sha=local_head.sha):
        raise LocalHeadNotPushedError(sha=local_head.sha)
    return local_head.sha


def _api_repo_path(*, repo: str | None) -> str:
    if repo is None:
        return "{owner}/{repo}"  # gh fills these placeholders in from the current checkout's remote
    return repo


def _resolve_commit(*, sha: str, repo: str | None, env: dict[str, str], deadline: float) -> str:
    completed = _gh(
        "api", f"repos/{_api_repo_path(repo=repo)}/commits/{sha}", "--jq", ".sha", env=env, deadline=deadline
    )
    if completed.returncode != 0:
        if "No commit found" in completed.stderr:
            raise UnknownCommitError(sha=sha)
        raise _gh_failure(stderr=completed.stderr)
    full_sha = completed.stdout.strip()
    if len(full_sha) != FULL_SHA_LENGTH:
        raise _unexpected_output(command="gh api repos/.../commits", stdout=completed.stdout)
    return full_sha


def _runs(*, commit_sha: str, repo: str | None, env: dict[str, str], deadline: float) -> list[_Run]:
    completed = _gh(
        "run",
        "list",
        "--commit",
        commit_sha,
        *_repo_args(repo=repo),
        "--limit",
        "100",
        "--json",
        "databaseId,status,conclusion,workflowName,event,createdAt",
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    command = "gh run list"
    error = _unexpected_output(command=command, stdout=completed.stdout)
    return [
        _Run(
            run_id=_int_field(obj=item, key="databaseId", error=error),
            status=_string_field(obj=item, key="status", error=error),
            conclusion=_string_field(obj=item, key="conclusion", error=error),
            workflow_name=_string_field(obj=item, key="workflowName", error=error),
            event=_string_field(obj=item, key="event", error=error),
            created_at=_string_field(obj=item, key="createdAt", error=error),
        )
        for item in _json_objects(command=command, stdout=completed.stdout)
    ]


def _open_prs_headed_at(*, commit_sha: str, repo: str | None, env: dict[str, str], deadline: float) -> list[int]:
    completed = _gh(
        "api",
        f"repos/{_api_repo_path(repo=repo)}/commits/{commit_sha}/pulls",
        "--jq",
        f'[.[] | select(.state == "open") | select(.head.sha == "{commit_sha}") | .number]',
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    command = "gh api repos/.../commits/.../pulls"
    error = _unexpected_output(command=command, stdout=completed.stdout)
    parsed = _parse_json(command=command, stdout=completed.stdout)
    if not isinstance(parsed, list):
        raise error
    numbers: list[int] = []
    item: object  # isinstance only narrows parsed to a list of unknowns; object is true of any JSON value
    for item in parsed:
        if not isinstance(item, int):
            raise error
        numbers.append(item)
    return numbers


def _any_pull_request_run(*, runs: list[_Run]) -> bool:
    for run in runs:
        if run.event == "pull_request":
            return True
        if run.event == "pull_request_target":
            return True
    return False


def _jobs(*, run_id: int, repo: str | None, env: dict[str, str], deadline: float) -> list[_Job]:
    completed = _gh(
        "run",
        "view",
        str(run_id),
        *_repo_args(repo=repo),
        "--json",
        "jobs",
        "--jq",
        ".jobs",
        env=env,
        deadline=deadline,
    )
    if completed.returncode != 0:
        raise _gh_failure(stderr=completed.stderr)
    command = "gh run view"
    error = _unexpected_output(command=command, stdout=completed.stdout)
    return [
        _Job(
            name=_string_field(obj=item, key="name", error=error),
            status=_string_field(obj=item, key="status", error=error),
            conclusion=_string_field(obj=item, key="conclusion", error=error),
        )
        for item in _json_objects(command=command, stdout=completed.stdout)
    ]


def _is_failed_conclusion(*, conclusion: str) -> bool:
    if conclusion in _FAILED_CONCLUSIONS:
        return True
    return False


def _failed_job_names(*, runs: list[_Run], repo: str | None, env: dict[str, str], deadline: float) -> list[str]:
    names: list[str] = []
    for run in runs:
        if run.status == "completed":
            if not _is_failed_conclusion(conclusion=run.conclusion):
                continue
        run_failures = [
            job.name
            for job in _jobs(run_id=run.run_id, repo=repo, env=env, deadline=deadline)
            if _is_failed_conclusion(conclusion=job.conclusion)
        ]
        # a run can fail before any job exists, such as on an invalid workflow file
        if len(run_failures) == 0:
            if run.status == "completed":
                run_failures.append(f"{run.workflow_name} ({run.conclusion})")
        names.extend(run_failures)
    return names


def _commit_session(*, sha: str, repo: str | None, deadline: float, state: _PollState) -> tuple[dict[str, str], str]:
    if state.gh_env is not None:
        if state.commit_sha is not None:
            return state.gh_env, state.commit_sha
    gh_env, commit_sha = _select_gh_env(
        probe=lambda env: _resolve_commit(sha=sha, repo=repo, env=env, deadline=deadline)
    )
    state.gh_env = gh_env
    state.commit_sha = commit_sha
    return gh_env, commit_sha


def _commit_poll(*, sha: str, repo: str | None, deadline: float, state: _PollState) -> tuple[str, int] | None:
    gh_env, commit_sha = _commit_session(sha=sha, repo=repo, deadline=deadline, state=state)
    return _commit_result(
        commit_sha=commit_sha,
        access=_RepoAccess(repo=repo, gh_env=gh_env, deadline=deadline),
        state=state,
        pr_created_at=None,
    )


def _commit_result(
    *, commit_sha: str, access: _RepoAccess, state: _PollState, pr_created_at: str | None
) -> tuple[str, int] | None:
    """Judge one commit's CI from its workflow runs.

    pr_created_at is None in commit mode. In PR mode it is the creation time of the PR whose head has moved past this
    commit, which brings in the rules for a superseded commit: no runs at all for a few polls means it was never the
    tip of a push, and a pull_request run is required only if the commit was pushed while the PR existed.
    """
    runs = _runs(commit_sha=commit_sha, repo=access.repo, env=access.gh_env, deadline=access.deadline)
    failed = _failed_job_names(runs=runs, repo=access.repo, env=access.gh_env, deadline=access.deadline)
    if len(failed) > 0:
        return f"CHECKS_FAILED: {', '.join(failed)}", 1
    if pr_created_at is not None:
        if len(runs) == 0:
            state.empty_run_polls += 1
            if state.empty_run_polls >= NO_RUNS_GRACE_POLLS:
                return f"NO_RUNS: {commit_sha} was never the tip of a push, so CI never ran on it", 1
    state.timeout_detail = _unfinished_runs_detail(runs=runs, commit_sha=commit_sha)
    if state.timeout_detail is not None:
        return None
    if not _any_pull_request_run(runs=runs):
        state.timeout_detail = _missing_pull_request_run_detail(
            commit_sha=commit_sha, access=access, runs=runs, pr_created_at=pr_created_at
        )
        if state.timeout_detail is not None:
            return None
    return "CHECKS_PASSED", 0


def _missing_pull_request_run_detail(
    *, commit_sha: str, access: _RepoAccess, runs: list[_Run], pr_created_at: str | None
) -> str | None:
    if pr_created_at is not None:
        if _push_runs_predate(runs=runs, moment=pr_created_at):
            return None
        return f"no pull_request run for {commit_sha} yet"
    open_prs = _open_prs_headed_at(commit_sha=commit_sha, repo=access.repo, env=access.gh_env, deadline=access.deadline)
    if len(open_prs) > 0:
        return f"PR #{open_prs[0]} is open for {commit_sha} but no pull_request run has appeared"
    return None


def _push_runs_predate(*, runs: list[_Run], moment: str) -> bool:
    cutoff = datetime.datetime.fromisoformat(moment)
    found_push_run = False
    for run in runs:
        if run.event != "push":
            continue
        found_push_run = True
        if datetime.datetime.fromisoformat(run.created_at) >= cutoff:
            return False
    return found_push_run


def _timed_out_line(*, deadline_minutes: float, state: _PollState) -> str:
    line = f"TIMED_OUT after {deadline_minutes:g} minutes"
    if state.timeout_detail is None:
        return line
    return f"{line}: {state.timeout_detail}"


def wait_for_ci(*, pr: str | None, repo: str | None, sha: str | None, deadline_minutes: float) -> tuple[str, int]:
    deadline = time.monotonic() + deadline_minutes * 60
    state = _PollState()
    if pr is not None:
        target = _Target(
            pr=pr, repo=repo, sha=sha, local_head=_awaited_local_head(sha=sha, repo=repo), deadline=deadline
        )
        return _poll_until_settled(
            poll=lambda: _pr_poll(target=target, state=state),
            deadline=deadline,
            deadline_minutes=deadline_minutes,
            state=state,
        )
    try:
        commit_sha = _commit_to_await(sha=sha)
    except LocalHeadNotPushedError as e:
        return f"LOCAL_HEAD_NOT_PUSHED: {e.sha}", 1
    return _poll_until_settled(
        poll=lambda: _commit_poll(sha=commit_sha, repo=repo, deadline=deadline, state=state),
        deadline=deadline,
        deadline_minutes=deadline_minutes,
        state=state,
    )


def _poll_until_settled(
    *, poll: Callable[[], tuple[str, int] | None], deadline: float, deadline_minutes: float, state: _PollState
) -> tuple[str, int]:
    consecutive_failed_polls = 0
    while True:
        try:
            result = poll()
        except GhNotFoundError as e:
            return f"GH_NOT_FOUND: {e}", 1
        except GhCallFailedError as e:
            consecutive_failed_polls += 1
            if consecutive_failed_polls >= MAX_CONSECUTIVE_FAILED_POLLS:
                return f"GH_UNREACHABLE: {e}", 1
        except LocalHeadNotPushedError as e:
            return f"LOCAL_HEAD_NOT_PUSHED: {e.sha}", 1
        except UnknownCommitError as e:
            return f"UNKNOWN_COMMIT: {e.sha}", 1
        else:
            if result is not None:
                return result
            consecutive_failed_polls = 0
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return _timed_out_line(deadline_minutes=deadline_minutes, state=state), 1
        time.sleep(min(POLL_SECONDS, remaining_seconds))


def _repo_from_pr_url(*, pr: str | None) -> str | None:
    if pr is None:
        return None
    match = _PR_URL_REPO.match(pr)
    if match is None:
        return None
    return match.group("repo")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument(
        "pr",
        nargs="?",
        help="PR number, URL or branch, as `gh pr view` accepts (a github.com URL also sets --repo, unless given);"
        " omit to wait on a commit's runs",
    )
    _ = parser.add_argument("--repo", help="OWNER/NAME of a repo other than the current checkout's")
    _ = parser.add_argument("--sha", help="the commit (full or abbreviated) whose checks to wait for")
    _ = parser.add_argument("--deadline-minutes", type=float, default=DEFAULT_DEADLINE_MINUTES)
    args = parser.parse_args()
    # gh pr view/checks follow a URL to its repo, but gh run list, gh api and the local-HEAD default would otherwise
    # read this checkout's
    if args.repo is None:
        args.repo = _repo_from_pr_url(pr=args.pr)
    if args.pr is None:
        if args.repo is not None:
            if args.sha is None:
                parser.error("without a PR, --repo needs --sha: the local HEAD says nothing about another repo")
    result_line, exit_code = wait_for_ci(
        pr=args.pr, repo=args.repo, sha=args.sha, deadline_minutes=args.deadline_minutes
    )
    print(result_line)  # noqa: T201 # the single result line is this script's whole output
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
