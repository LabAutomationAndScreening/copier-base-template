import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

GH_TIMEOUT_SECONDS = 30

# Findings from an AI code review are posted under the account of the person who ran the review, so their author is
# the current user. This hidden marker is how read.py tells such a finding (still awaiting a response) apart from the
# user's own replies (which mark a thread as addressed).
_AI_REVIEW_FINDING_RE = re.compile(
    r"<!-- ai-review-finding id=(?P<id>[A-Za-z0-9_-]+)(?: related=(?P<related>[A-Za-z0-9_,-]+))? -->"
)

# GitHub has no threading for top-level PR comments, so a reply to one is a new top-level comment carrying this hidden
# marker, which lets read.py treat the original as addressed. post.py writes it.
_ISSUE_COMMENT_REPLY_RE = re.compile(r"<!-- reply-to-issue-comment id=(?P<id>\d+) -->")

# An independent verifier posts its verdict on a reply to an AI review finding under the same account as the reply,
# so this hidden marker is how read.py tells a verdict apart from the reply it judges: a disagreement reopens the
# thread instead of counting as the user having addressed it.
_AI_REVIEW_VERDICT_RE = re.compile(
    r"<!-- ai-review-verdict finding=(?P<finding>[A-Za-z0-9_-]+) verdict=(?P<verdict>accept|disagree) "
    r"round=(?P<round>\d+) -->"
)
VERDICT_ACCEPT = "accept"
VERDICT_DISAGREE = "disagree"

_MODEL_ID_RE = re.compile(r"claude-(?P<family>[a-z]+)-(?P<major>\d+)(?:-(?P<minor>\d{1,2}))?(?:-\d{8})?")


@dataclass(frozen=True)
class AiReviewFinding:
    finding_id: str
    related_ids: tuple[str, ...]


@dataclass(frozen=True)
class AiReviewVerdict:
    finding_id: str
    verdict: str
    round: int


def ai_review_verdict_marker(*, finding_id: str, verdict: str, round_number: int) -> str:
    return f"<!-- ai-review-verdict finding={finding_id} verdict={verdict} round={round_number} -->"


def parse_ai_review_verdict(body: str) -> AiReviewVerdict | None:
    match = _AI_REVIEW_VERDICT_RE.search(body)
    if match is None:
        return None
    return AiReviewVerdict(
        finding_id=match.group("finding"), verdict=match.group("verdict"), round=int(match.group("round"))
    )


def model_display_name(model_id: str) -> str:
    match = _MODEL_ID_RE.fullmatch(model_id)
    if match is None:
        return model_id
    version = match.group("major")
    if match.group("minor") is not None:
        version = f"{version}.{match.group('minor')}"
    return f"Claude {match.group('family').title()} {version}"


def describe_model(*, model: str | None, effort: str | None) -> str:
    """Describe the model and effort level behind an AI comment, for the line that opens it.

    For example "Claude Opus 5.5 (`claude-opus-5-5`) at max effort". `model` may list several comma-separated model
    IDs, when more than one model wrote a review.
    """
    if model is None:
        return "an unknown model"
    models: list[str] = []
    for model_id in model.split(", "):
        name = model_display_name(model_id)
        models.append(f"`{model_id}`" if name == model_id else f"{name} (`{model_id}`)")
    description = " and ".join(models)
    if effort is not None:
        description += f" at {effort} effort"
    return description


def ai_review_finding_marker(*, finding_id: str, related_ids: Sequence[str]) -> str:
    if related_ids:
        return f"<!-- ai-review-finding id={finding_id} related={','.join(related_ids)} -->"
    return f"<!-- ai-review-finding id={finding_id} -->"


def parse_ai_review_finding(body: str) -> AiReviewFinding | None:
    match = _AI_REVIEW_FINDING_RE.search(body)
    if match is None:
        return None
    related = match.group("related")
    if related is None:
        return AiReviewFinding(finding_id=match.group("id"), related_ids=())
    return AiReviewFinding(finding_id=match.group("id"), related_ids=tuple(related.split(",")))


def issue_comment_reply_marker(comment_id: int) -> str:
    return f"<!-- reply-to-issue-comment id={comment_id} -->"


def parse_issue_comment_reply(body: str) -> int | None:
    match = _ISSUE_COMMENT_REPLY_RE.search(body)
    if match is None:
        return None
    return int(match.group("id"))


_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
# gh's exit status when it has no credentials at all (`gh help exit-codes`)
_GH_EXIT_AUTH_REQUIRED = 4


def _without_tokens() -> dict[str, str]:
    env = dict(os.environ)
    for name in _TOKEN_NAMES:
        _ = env.pop(name, None)
    return env


def _tokens_in_env() -> bool:
    for name in _TOKEN_NAMES:
        if name in os.environ:
            return True
    return False


def _run_gh(args: list[str], *, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — gh is the only executable, and every value is passed as a separate argument
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=timeout,
        env=env,
    )


def gh_run(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run a gh command, preferring the login `gh auth login` stored over the environment's tokens.

    gh itself prefers GH_TOKEN and GITHUB_TOKEN, and the GITHUB_TOKEN a codespace injects reaches only the codespace's
    own repository, so the first try runs without them and uses the stored login, which reaches every repo the user
    can. When gh reports that it has no credentials at all and the environment holds a token, that token is all there
    is, so the command runs again with it.

    Raises subprocess.CalledProcessError when the command fails, as check=True would.
    """
    result = _run_gh(args, timeout=timeout, env=_without_tokens())
    if result.returncode == _GH_EXIT_AUTH_REQUIRED and _tokens_in_env():
        result = _run_gh(args, timeout=timeout, env=dict(os.environ))
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, output=result.stdout, stderr=result.stderr)
    return result


def gh_rest(*args: str) -> Any:  # noqa: ANN401 — return type is genuinely unknown JSON
    # --paginate emits one JSON doc per page; --slurp wraps them into a single array.
    # Each page is itself an array, so we flatten the resulting array-of-arrays.
    paginating = "--paginate" in args
    call_args = [*args, "--slurp"] if paginating else list(args)
    result = gh_run(["gh", *call_args], timeout=GH_TIMEOUT_SECONDS)
    data = json.loads(result.stdout)
    if not paginating:
        return data
    # --slurp wraps each page (a list) into an outer list; flatten to a single list.
    # All --paginate call sites query list endpoints, so data is list[list[Any]].
    return [item for page in data for item in page]


def gh_graphql(query: str, variables: Mapping[str, str | int | bool]) -> Any:  # noqa: ANN401 — return type is genuinely unknown JSON
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        # -F for integers and booleans (GraphQL Int/Boolean), -f for strings
        flag = "-f" if isinstance(value, str) else "-F"
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        args += [flag, f"{key}={rendered}"]
    result = gh_run(args, timeout=GH_TIMEOUT_SECONDS)
    data = json.loads(result.stdout)
    if errors := data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {errors}")
    return data["data"]


def run_cmd(
    cmd: list[str],
    *,
    timeout: int,
    timeout_msg: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — callers are responsible for only passing safe commands
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(f"{timeout_msg}\n")
        sys.exit(1)


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_count: int


def parse_hunks(diff_text: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    for diff_line in diff_text.splitlines():
        match = HUNK_HEADER_RE.match(diff_line)
        if match is None:
            continue
        old_count, new_count = match.group(2), match.group(4)
        hunks.append(
            Hunk(
                old_start=int(match.group(1)),
                old_count=1 if old_count is None else int(old_count),
                new_count=1 if new_count is None else int(new_count),
            )
        )
    return hunks


def map_line(*, hunks: list[Hunk], line: int) -> int | None:
    """Map a line number on the old side of a zero-context diff to the new side.

    Returns None when the line itself was changed or deleted, since then there is no line it unambiguously became.
    """
    offset = 0
    for hunk in hunks:
        if hunk.old_count == 0:
            # a pure insertion after line old_start
            if hunk.old_start < line:
                offset += hunk.new_count
                continue
            break
        if hunk.old_start + hunk.old_count - 1 < line:
            offset += hunk.new_count - hunk.old_count
            continue
        if hunk.old_start <= line:
            return None
        break
    return line + offset


def map_line_between(*, path: str, line: int, from_commit: str, to_commit: str) -> int | None:
    """Return where a file's line at from_commit is at to_commit, or None if that line was changed or deleted.

    Raises subprocess.CalledProcessError if git can't diff the two commits, e.g. one isn't available locally.
    """
    if from_commit == to_commit:
        return line
    diff = run_cmd(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "-U0",
            from_commit,
            to_commit,
            "--",
            path,
        ],
        timeout=GH_TIMEOUT_SECONDS,
        timeout_msg=f"Timed out diffing {path} between {from_commit} and {to_commit}.",
    ).stdout
    return map_line(hunks=parse_hunks(diff), line=line)


def owner_repo_from_remote() -> tuple[str, str]:
    try:
        result = run_cmd(
            ["git", "remote", "get-url", "origin"],
            timeout=15,
            timeout_msg="Timed out reading git remote 'origin'.",
        )
    except subprocess.CalledProcessError:
        _ = sys.stderr.write("Cannot read git remote 'origin'. Ensure it exists and points to GitHub.\n")
        sys.exit(1)
    url = result.stdout.strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?",
        url,
    )
    if not match:
        _ = sys.stderr.write(f"Cannot parse GitHub owner/repo from remote: {url}\n")
        sys.exit(1)
    return match.group(1), match.group(2)


_OWNER_REPO_RE = re.compile(r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)")


def owner_and_repo(*, repo: str | None) -> tuple[str, str]:
    """Return the owner and name of the repo a script acts on: `repo` as OWNER/NAME, else the origin remote's."""
    if repo is None:
        return owner_repo_from_remote()
    match = _OWNER_REPO_RE.fullmatch(repo)
    if match is None:
        _ = sys.stderr.write(f"--repo must be OWNER/NAME, not {repo}\n")
        sys.exit(1)
    return match.group("owner"), match.group("repo")


COMMIT_LINK_PLACEHOLDER = "[COMMIT LINK]"


def pr_commit_link(*, owner: str, repo: str, pr: int, commit: str) -> str:
    """Return a markdown link to a commit as it appears in the PR.

    GitHub redirects /pull/<pr>/changes/<commit> to the PR-scoped view of the commit, so a comment made against it
    belongs to the PR, which a /commit/<commit> link does not give. The link has to be markdown: GitHub rewrites a
    bare PR-scoped URL to the repo-wide commit view.
    """
    return f"[{commit[:7]}](https://github.com/{owner}/{repo}/pull/{pr}/changes/{commit})"
