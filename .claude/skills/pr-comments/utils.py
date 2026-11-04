import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GH_TIMEOUT_SECONDS = 30

# Findings from an AI code review are posted under the account of the person who ran the review, so their author is
# the current user. This hidden marker is how read.py tells such a finding (still awaiting a response) apart from the
# user's own replies (which mark a thread as addressed).
_AI_REVIEW_FINDING_RE = re.compile(
    r"<!-- ai-review-finding id=(?P<id>[A-Za-z0-9_-]+)(?: related=(?P<related>[A-Za-z0-9_,-]+))? -->"
)

# GitHub has no threading for top-level PR comments, so a reply to one is a new top-level comment carrying this hidden
# marker, which lets read.py treat the original as addressed. post.py writes it as the body's last line, and only a
# marker there counts: one quoted earlier in a comment, such as a reply explaining the markers, answers nothing.
_ISSUE_COMMENT_REPLY_RE = re.compile(r"<!-- reply-to-issue-comment id=(?P<id>\d+) -->\s*\Z")
# A review's own body has no thread either, so a reply to it is a top-level comment ending in this marker, by the same
# logic.
_REVIEW_REPLY_RE = re.compile(r"<!-- reply-to-review id=(?P<id>\d+) -->\s*\Z")

# An independent verifier posts its verdict on a reply to an AI review finding under the same account as the reply,
# so this hidden marker is how read.py tells a verdict apart from the reply it judges: a disagreement reopens the
# thread instead of counting as the user having addressed it.
_AI_REVIEW_VERDICT_RE = re.compile(
    r"<!-- ai-review-verdict finding=(?P<finding>[A-Za-z0-9_-]+) verdict=(?P<verdict>accept|disagree) "
    r"round=(?P<round>\d+) -->"
)
VERDICT_ACCEPT = "accept"
VERDICT_DISAGREE = "disagree"
# after this many verdicts on a thread, it is left to the user rather than verified again
MAX_VERDICT_ROUNDS = 2

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


def review_reply_marker(review_id: int) -> str:
    return f"<!-- reply-to-review id={review_id} -->"


def parse_review_reply(body: str) -> int | None:
    match = _REVIEW_REPLY_RE.search(body)
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
            encoding="utf-8",
            errors="replace",
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


def add_repo_arguments(parser: argparse.ArgumentParser) -> None:
    """Add --repo and --checkout, the two ways a script is told which repo the PR belongs to."""
    repo_source = parser.add_mutually_exclusive_group()
    _ = repo_source.add_argument(
        "--repo", default=None, metavar="OWNER/NAME", help="the PR's repo (default: the origin remote's)"
    )
    _ = repo_source.add_argument(
        "--checkout", type=Path, default=None, help="a checkout of the PR's repo, to act on as if run from there"
    )


def enter_checkout(checkout: Path | None) -> None:
    """Make `checkout` the current directory, so git, gh and the origin remote all act on the repo checked out there.

    A caller such as the backport-copier-change skill works on a PR in another repo, cloned under its scratchpad. The
    scripts still run from the originating repo, since that clone may carry an older copy of them, or none. Child
    processes inherit the new directory, so the scripts a script runs act on the checkout too.
    """
    if checkout is None:
        return
    if not checkout.is_dir():
        _ = sys.stderr.write(f"--checkout {checkout} is not a directory\n")
        sys.exit(1)
    os.chdir(checkout)


COMMIT_LINK_PLACEHOLDER = "[COMMIT LINK]"


def pr_commit_link(*, owner: str, repo: str, pr: int, commit: str) -> str:
    """Return a markdown link to a commit as it appears in the PR.

    /pull/<pr>/commits/<commit> is the PR-scoped view of the commit, so a comment made against it belongs to the PR,
    which a /commit/<commit> link does not give. The link has to be markdown: GitHub rewrites a bare PR-scoped URL to
    the repo-wide commit view.
    """
    return f"[{commit[:7]}](https://github.com/{owner}/{repo}/pull/{pr}/commits/{commit})"


# Markdown code: a fenced block, opened by a line starting with 3+ backticks or tildes (a backtick fence's info string
# holds no backtick) and closed by a line of at least as many of the same character (or running to the end, as GitHub
# renders an unclosed fence), or an inline code span opened and closed by whole backtick runs of the same length. A
# backslash-escaped backtick is literal text and opens no span; one closes a span, since backslashes inside code are
# literal too.
_CODE_RE = re.compile(
    r"^ {0,3}(?P<fence>(?P<fence_char>[`~])(?P=fence_char){2,})(?:(?<=`)[^`\n]*|(?<=~)[^\n]*)$"
    r"(?:\n.*?^ {0,3}(?P=fence)(?P=fence_char)*[ \t]*$|.*\Z)"
    r"|(?<![`\\])(?P<ticks>`+)(?!`).+?(?<!`)(?P=ticks)(?!`)",
    re.DOTALL | re.MULTILINE,
)
# A reviewer's block of instructions written for AI agents: CodeRabbit wraps it in these markers, and its older
# reviews put it in a <details> block whose summary says so.
_AI_AGENT_PROMPT_RE = re.compile(
    r"<!-- ai-agent-prompt:start -->.*?<!-- ai-agent-prompt:end -->"
    r"|<details>\s*<summary>(?:(?!</summary>).)*Prompt for AI Agents(?:(?!</summary>).)*</summary>.*?</details>",
    re.DOTALL,
)
# The scripts CodeRabbit ran while checking a finding, and their output: how it got there, not what it found.
_ANALYSIS_CHAIN_RE = re.compile(
    r"<details>\s*<summary>(?:(?!</summary>).)*Analysis chain(?:(?!</summary>).)*</summary>.*?</details>", re.DOTALL
)
# CodeRabbit ends a review body with machinery rather than findings: a fix-everything checkbox, a prompt covering
# every comment, and its "Review info" (configuration, commits, files processed).
_REVIEW_FOOTER_RE = re.compile(
    r"<!-- autofix_checkbox_start -->|<details>\s*<summary>(?:(?!</summary>).)*Review info", re.DOTALL
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PICTURE_RE = re.compile(r"<picture>.*?</picture>", re.DOTALL)
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>\n]*)?/?>")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_BLANK_QUOTE_LINES_RE = re.compile(r"^(?:>[ \t]*\n){2,}", re.MULTILINE)


def split_code(content: str) -> list[tuple[str, bool]]:
    """Split Markdown into (text, is_code) pieces, in order.

    Fenced blocks and inline code spans are code, as Markdown reads them; the text between them is prose. The pieces
    join back into the content unchanged.
    """
    pieces: list[tuple[str, bool]] = []
    end_of_previous = 0
    for code in _CODE_RE.finditer(content):
        pieces.append((content[end_of_previous : code.start()], False))
        pieces.append((code.group(0), True))
        end_of_previous = code.end()
    pieces.append((content[end_of_previous:], False))
    return pieces


def count_commit_link_placeholders(content: str) -> int:
    """Count the [COMMIT LINK] placeholders in a reply's prose.

    One inside a code span or a fenced block is text about the placeholder, as in a reply explaining how replies link
    their commits: it is not counted, and fill_commit_link_placeholders leaves it as written.
    """
    count = 0
    for text, is_code in split_code(content):
        if not is_code:
            count += text.count(COMMIT_LINK_PLACEHOLDER)
    return count


def fill_commit_link_placeholders(content: str, *, link: str) -> str:
    filled: list[str] = []
    for text, is_code in split_code(content):
        if is_code:
            filled.append(text)
        else:
            filled.append(text.replace(COMMIT_LINK_PLACEHOLDER, link))
    return "".join(filled)


def strip_markup(body: str) -> str:
    """Return a comment body as readable text: its Markdown with the reviewer's machinery removed.

    Removed whole, code included: everything from a review body's closing machinery on, the block of instructions a
    reviewer writes for AI agents, and the scripts it ran to check a finding. Then, in prose only (code spans and
    fenced blocks stay as written): HTML comments (hidden markers and fingerprints), decorative <picture> icons, and
    HTML tags (the text inside a <details> or <summary> stays). Runs of blank lines left behind, quoted or not,
    collapse to one.
    """
    footer = _REVIEW_FOOTER_RE.search(body)
    if footer is not None:
        body = body[: footer.start()]
    body = _ANALYSIS_CHAIN_RE.sub("", _AI_AGENT_PROMPT_RE.sub("", body))
    stripped: list[str] = []
    for text, is_code in split_code(body):
        if is_code:
            stripped.append(text)
            continue
        prose = _HTML_COMMENT_RE.sub("", text)
        prose = _PICTURE_RE.sub("", prose)
        prose = _HTML_TAG_RE.sub("", prose)
        prose = _BLANK_QUOTE_LINES_RE.sub(">\n", prose)
        stripped.append(_BLANK_LINES_RE.sub("\n\n", prose))
    return "".join(stripped).strip()
