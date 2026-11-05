#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Post the findings of a /code-review run to a PR as one review, attributed to the AI reviewer.

Usage:
  post_review.py import --from <file> --pr <number> --commit <sha> --out <findings file> [--model <id>] [--effort <level>]
  post_review.py plan --findings-file <findings file> [--preview <markdown file>] [--resume]
  post_review.py post --findings-file <findings file> --head <approved pr_head> --base <approved pr_base> [--resume]

import  Reads either a file holding the JSON array of findings /code-review reports, or the transcript of the
        /code-review agent (the .jsonl output file named in its task notification, whose final message holds that
        array in a ```json block). Writes a findings file:
          {"pr", "reviewed_commit", "reviewer": {"model", "effort"}, "summary", "findings": [{"id", "file", "line",
           "category", "short_summary", "summary", "failure_scenario", "related": [{"id", "note"}]}]}
        `reviewer` is the model and effort level that ran the review, which every posted comment names in its first
        line. A transcript records them; for a bare array pass --model (and --effort), which also override the
        transcript.
        IDs (F1, F2, ...) are numbered after any finding IDs already on the PR. `summary` (the review body) and each
        `related` list start empty for the agent to fill in. A finding may also carry `line_commit`, the commit its
        `line` refers to, when that is not reviewed_commit.
plan    Prints, as JSON, where each finding would be posted and anything that must be resolved first. Posts nothing.
        With --preview, also writes the review body and every comment, exactly as they would be posted, to a
        markdown file for the user to read.
post    Re-runs the plan and refuses if anything needs attention, or if the PR head or base is no longer the --head or
        --base the user approved (a push since can move the anchor or fix a finding, and a moved base changes which
        lines are in the diff, so where a finding is posted). Then creates a pending review on the anchor
        commit, adds every finding as a thread (or as a top-level PR comment when its file is not in the PR), fills
        in the links between related findings now that their URLs exist, and submits the review as a COMMENT. If
        anything fails, it reads the review's state: still pending means everything it created is deleted;
        submitted (GitHub can apply a submit yet return an empty response) means the post succeeded; unreadable
        means nothing is deleted. On success the posted URLs are written back into the findings file, and a
        findings file that has been posted is refused next time.
        With --resume, findings whose IDs are already on the PR are skipped and the rest are posted as a new
        review. Links are filled in both ways, editing the earlier findings that point at a newly posted one.

Placement is computed against the reviewed commit. If that commit is still in the PR, the review is pinned to it, so
line numbers are never recomputed and GitHub shows findings on code changed since as outdated. If the branch was
rewritten and the commit is no longer in the PR, the review is anchored to the PR head instead and each line is
mapped forward through the diff; a line inside changed code cannot be mapped and needs attention.
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "pr-comments"))
from utils import FINDING_ID_PATTERN
from utils import GH_TIMEOUT_SECONDS
from utils import HUNK_HEADER_RE
from utils import ai_review_finding_marker
from utils import describe_model
from utils import gh_graphql
from utils import gh_rest
from utils import map_line_between
from utils import owner_repo_from_remote
from utils import parse_ai_review_finding

FINDING_ID_PREFIX = "F"
SHORT_SHA_LENGTH = 7
TABLE_SUMMARY_MAX_LENGTH = 120
_FINDING_NUMBER_RE = re.compile(rf"{FINDING_ID_PREFIX}(\d+)")
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)

POSTED_UNDER_NOTE = "<sub>Posted under the account of the person who ran the review.</sub>"

PR_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $repo) {
    visibility
    pullRequest(number: $number) {
      id
      state
      headRefOid
      baseRefOid
      reviews(states: [PENDING], first: 20) { nodes { id author { login } } }
    }
  }
}
"""
ADD_REVIEW = """
mutation($pullRequestId: ID!, $commitOID: GitObjectID!) {
  addPullRequestReview(input: {pullRequestId: $pullRequestId, commitOID: $commitOID}) { pullRequestReview { id } }
}
"""
ADD_LINE_THREAD = """
mutation($reviewId: ID!, $path: String!, $line: Int!, $body: String!) {
  addPullRequestReviewThread(input: {
    pullRequestReviewId: $reviewId, path: $path, line: $line, side: RIGHT, subjectType: LINE, body: $body
  }) { thread { comments(first: 1) { nodes { id url } } } }
}
"""
ADD_FILE_THREAD = """
mutation($reviewId: ID!, $path: String!, $body: String!) {
  addPullRequestReviewThread(input: {pullRequestReviewId: $reviewId, path: $path, subjectType: FILE, body: $body}) {
    thread { comments(first: 1) { nodes { id url } } }
  }
}
"""
ADD_PR_COMMENT = """
mutation($subjectId: ID!, $body: String!) {
  addComment(input: {subjectId: $subjectId, body: $body}) { commentEdge { node { id url } } }
}
"""
UPDATE_REVIEW_COMMENT = """
mutation($id: ID!, $body: String!) {
  updatePullRequestReviewComment(input: {pullRequestReviewCommentId: $id, body: $body}) { pullRequestReviewComment { id } }
}
"""
UPDATE_PR_COMMENT = """
mutation($id: ID!, $body: String!) {
  updateIssueComment(input: {id: $id, body: $body}) { issueComment { id } }
}
"""
SUBMIT_REVIEW = """
mutation($reviewId: ID!, $body: String!) {
  submitPullRequestReview(input: {pullRequestReviewId: $reviewId, event: COMMENT, body: $body}) {
    pullRequestReview { url }
  }
}
"""
REVIEW_STATE = """
query($id: ID!) { node(id: $id) { ... on PullRequestReview { state url } } }
"""
DELETE_REVIEW = """
mutation($reviewId: ID!) { deletePullRequestReview(input: {pullRequestReviewId: $reviewId}) { pullRequestReview { id } } }
"""
DELETE_PR_COMMENT = """
mutation($id: ID!) { deleteIssueComment(input: {id: $id}) { clientMutationId } }
"""


class InputError(Exception):
    pass


@dataclass(frozen=True)
class Related:
    finding_id: str
    note: str


@dataclass
class Finding:
    finding_id: str
    file: str
    line: int | None
    line_commit: str | None
    category: str | None
    short_summary: str | None
    summary: str
    failure_scenario: str
    related: list[Related] = field(default_factory=list)


@dataclass(frozen=True)
class Reviewer:
    model: str | None
    effort: str | None


@dataclass
class FindingsFile:
    pr: int
    reviewed_commit: str
    reviewer: Reviewer
    summary: str
    findings: list[Finding]
    posted: dict[str, Any] | None


@dataclass
class PlannedFinding:
    finding: Finding
    placement: str
    line_at_anchor: int | None
    changed_since_review: bool
    attention: str | None


@dataclass(frozen=True)
class PostedComment:
    node_id: str
    url: str
    is_review_comment: bool


@dataclass
class Plan:
    pr_node_id: str
    pr_head: str
    pr_base: str
    anchor_commit: str
    reviewed_commit_in_pr: bool
    visibility: str
    reviewer_model: str | None
    pending_review_ids: list[str]
    existing_findings: dict[str, PostedComment]
    planned: list[PlannedFinding]

    def already_posted(self, *, resume: bool) -> dict[str, PostedComment]:
        """Return the comments of this file's findings that are already on the PR, keyed by finding ID.

        Only a resumed post skips those findings. Otherwise their IDs are collisions that block posting, so nothing
        counts as already posted and this is empty.
        """
        if not resume:
            return {}
        planned_ids = {p.finding.finding_id for p in self.planned}
        return {finding_id: c for finding_id, c in self.existing_findings.items() if finding_id in planned_ids}

    def earlier_findings_to_relink(self, *, resume: bool) -> list[str]:
        """Return the IDs of findings already on the PR that are related to a finding this post adds.

        A resumed post edits their comments so that their links reach the new findings, and GitHub marks those
        comments edited.
        """
        already_posted = self.already_posted(resume=resume)
        new_ids = {p.finding.finding_id for p in self.planned} - already_posted.keys()
        return [
            p.finding.finding_id
            for p in self.planned
            if p.finding.finding_id in already_posted and {r.finding_id for r in p.finding.related} & new_ids
        ]

    def blocking_problems(self, *, resume: bool) -> list[str]:
        problems: list[str] = []
        if self.reviewer_model is None:
            problems.append(
                "The model that ran the review is unknown, and every comment names it. Set `reviewer.model` in the "
                "findings file to its model ID."
            )
        if self.pending_review_ids:
            problems.append(
                "You already have a pending review on this PR. Submit or discard it in the GitHub UI first: "
                "GitHub allows only one pending review per person per PR."
            )
        collisions = sorted({p.finding.finding_id for p in self.planned} & self.existing_findings.keys())
        if collisions and not resume:
            problems.append(
                f"Finding IDs already used on this PR: {', '.join(collisions)}. Renumber them, or, if they are this "
                "file's own findings from a post that did not finish, pass --resume to post only the rest."
            )
        problems.extend(f"{p.finding.finding_id}: {p.attention}" for p in self.planned if p.attention is not None)
        return problems


def _fail(message: str) -> None:
    _ = sys.stderr.write(f"{message}\n")
    sys.exit(1)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — git is the only executable, and every value is passed as a separate argument
        ["git", "-c", "core.quotepath=false", *args],  # noqa: S607 — git is expected on PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=GH_TIMEOUT_SECONDS,
    )


def _git_output(*args: str) -> str:
    result = _git(*args)
    if result.returncode != 0:
        _fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _ensure_commit(sha: str) -> str:
    if _git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        _ = _git_output("fetch", "--quiet", "origin", sha)
    return _git_output("rev-parse", f"{sha}^{{commit}}").strip()


def _is_ancestor(*, ancestor: str, descendant: str) -> bool:
    return _git("merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _file_exists_at(*, commit: str, path: str) -> bool:
    return _git("cat-file", "-e", f"{commit}:{path}").returncode == 0


def _commentable_lines(*, base: str, anchor: str) -> dict[str, set[int]]:
    """Return, for each file in the PR's diff at the anchor commit, the new-side lines GitHub lets a comment sit on.

    That is every line inside a hunk, context included, using the 3 lines of context GitHub's own diff shows. Rename
    detection is on, as it is on GitHub, so a renamed file is listed under its new path.
    """
    merge_base = _git_output("merge-base", base, anchor).strip()
    commentable: dict[str, set[int]] = {
        path: set() for path in _git_output("diff", "--name-only", "-M", merge_base, anchor).splitlines() if path
    }
    # the prefixes are pinned, so a user's diff.noprefix or diff.mnemonicPrefix can't change the headers parsed below
    diff = _git_output(
        "diff", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "-M", "-U3", merge_base, anchor
    )
    current_path: str | None = None
    # lines of the current hunk still to come on each side: until both run out, a line starting "+++ " is an added
    # line whose content starts "++ ", not a file header
    old_left = 0
    new_left = 0
    for diff_line in diff.splitlines():
        if old_left > 0 or new_left > 0:
            if diff_line.startswith("+"):
                new_left -= 1
            elif diff_line.startswith("-"):
                old_left -= 1
            elif not diff_line.startswith("\\"):  # "\ No newline at end of file" belongs to neither side
                old_left -= 1
                new_left -= 1
            continue
        if diff_line.startswith("+++ "):
            # git ends the header with a tab when the path has a space in it
            target = diff_line[len("+++ ") :].removesuffix("\t")
            current_path = target[len("b/") :] if target.startswith("b/") else None
            continue
        match = HUNK_HEADER_RE.match(diff_line)
        if match is None:
            continue
        old_left = 1 if match.group(2) is None else int(match.group(2))
        new_start = int(match.group(3))
        new_count = 1 if match.group(4) is None else int(match.group(4))
        new_left = new_count
        if current_path is None:
            continue
        commentable.setdefault(current_path, set()).update(range(new_start, new_start + new_count))
    return commentable


def _require_str(*, raw: dict[str, Any], key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise InputError(f"{context}: `{key}` must be a string")
    return value


def _optional_str(*, raw: dict[str, Any], key: str, context: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"{context}: `{key}` must be a string or null")
    return value


def _optional_line(*, raw: dict[str, Any], context: str) -> int | None:
    value = raw.get("line")
    if value is None:
        return None
    # bool is a subclass of int, and true/false is never a line number
    if isinstance(value, bool):
        raise InputError(f"{context}: `line` must be an integer or null")
    if not isinstance(value, int):
        raise InputError(f"{context}: `line` must be an integer or null")
    if value < 1:
        raise InputError(f"{context}: `line` must be a positive integer or null, not {value}")
    return value


def _require_finding_id(*, finding_id: str, context: str) -> str:
    if re.fullmatch(FINDING_ID_PATTERN, finding_id) is None:
        raise InputError(f"{context}: finding ID {finding_id!r} may hold only letters, digits, '_' and '-'")
    return finding_id


def _parse_related(*, raw: dict[str, Any], context: str) -> list[Related]:
    value = raw.get("related", [])
    if not isinstance(value, list):
        raise InputError(f"{context}: `related` must be a list")
    related: list[Related] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise InputError(f"{context}: each `related` entry must be an object with `id` and `note`")
        related.append(
            Related(
                finding_id=_require_finding_id(
                    finding_id=_require_str(raw=entry, key="id", context=context), context=context
                ),
                note=_require_str(raw=entry, key="note", context=context),
            )
        )
    return related


def _parse_finding(*, raw: object, finding_id: str | None, index: int) -> Finding:
    context = f"finding #{index + 1}"
    if not isinstance(raw, dict):
        raise InputError(f"{context}: must be an object")
    return Finding(
        finding_id=_require_finding_id(
            finding_id=_require_str(raw=raw, key="id", context=context) if finding_id is None else finding_id,
            context=context,
        ),
        file=_require_str(raw=raw, key="file", context=context),
        line=_optional_line(raw=raw, context=context),
        line_commit=_optional_str(raw=raw, key="line_commit", context=context),
        category=_optional_str(raw=raw, key="category", context=context),
        short_summary=_optional_str(raw=raw, key="short_summary", context=context),
        summary=_require_str(raw=raw, key="summary", context=context),
        failure_scenario=_require_str(raw=raw, key="failure_scenario", context=context),
        related=_parse_related(raw=raw, context=context),
    )


def load_findings_file(path: Path) -> FindingsFile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise InputError(f"{path} must hold a JSON object; create it with `post_review.py import`")
    pr = raw.get("pr")
    if not isinstance(pr, int):
        raise InputError("`pr` must be an integer")
    findings_raw = raw.get("findings")
    if not isinstance(findings_raw, list):
        raise InputError("`findings` must be a list")
    posted = raw.get("posted")
    if posted is not None and not isinstance(posted, dict):
        raise InputError("`posted` must be an object or absent")
    findings = [_parse_finding(raw=f, finding_id=None, index=i) for i, f in enumerate(findings_raw)]
    ids = [f.finding_id for f in findings]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise InputError(f"duplicate finding IDs: {', '.join(duplicates)}")
    known = set(ids)
    dangling = sorted({r.finding_id for f in findings for r in f.related} - known)
    if dangling:
        raise InputError(f"`related` names finding IDs that are not in this file: {', '.join(dangling)}")
    reviewer_raw = raw.get("reviewer", {})
    if not isinstance(reviewer_raw, dict):
        raise InputError("`reviewer` must be an object with `model` and `effort`")
    return FindingsFile(
        pr=pr,
        reviewed_commit=_require_str(raw=raw, key="reviewed_commit", context=str(path)),
        reviewer=Reviewer(
            model=_optional_str(raw=reviewer_raw, key="model", context="reviewer"),
            effort=_optional_str(raw=reviewer_raw, key="effort", context="reviewer"),
        ),
        summary=_optional_str(raw=raw, key="summary", context=str(path)) or "",
        findings=findings,
        posted=posted,
    )


def _findings_file_json(findings_file: FindingsFile) -> dict[str, Any]:
    result: dict[str, Any] = {
        "pr": findings_file.pr,
        "reviewed_commit": findings_file.reviewed_commit,
        "reviewer": {"model": findings_file.reviewer.model, "effort": findings_file.reviewer.effort},
        "summary": findings_file.summary,
        "findings": [
            {
                "id": f.finding_id,
                "file": f.file,
                "line": f.line,
                **({"line_commit": f.line_commit} if f.line_commit is not None else {}),
                "category": f.category,
                "short_summary": f.short_summary,
                "summary": f.summary,
                "failure_scenario": f.failure_scenario,
                "related": [{"id": r.finding_id, "note": r.note} for r in f.related],
            }
            for f in findings_file.findings
        ],
    }
    if findings_file.posted is not None:
        result["posted"] = findings_file.posted
    return result


def _write_findings_file(*, path: Path, findings_file: FindingsFile) -> None:
    _ = path.write_text(json.dumps(_findings_file_json(findings_file), indent=2, ensure_ascii=False) + "\n", "utf-8")


def _findings_array_from_transcript(text: str) -> list[Any]:
    last_block: str | None = None
    for transcript_line in text.splitlines():
        if not transcript_line.strip():
            continue
        entry = json.loads(transcript_line)
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            blocks = _JSON_BLOCK_RE.findall(block.get("text", ""))
            if blocks:
                last_block = blocks[-1]
    if last_block is None:
        raise InputError("no ```json block found in any assistant message of the transcript")
    findings = json.loads(last_block)
    if not isinstance(findings, list):
        raise InputError("the transcript's last ```json block is not a JSON array")
    return findings


def _reviewer_from_transcript(text: str) -> Reviewer:
    """Return the model(s) and effort level that a /code-review agent transcript records for its replies.

    Each assistant entry carries the model that wrote it. Claude Code also writes placeholder entries whose model is
    in angle brackets (e.g. `<synthetic>`); those are not a model and are skipped.
    """
    models: list[str] = []
    effort: str | None = None
    for transcript_line in text.splitlines():
        if not transcript_line.strip():
            continue
        entry = json.loads(transcript_line)
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            continue
        model = message.get("model")
        if isinstance(model, str) and not model.startswith("<") and model not in models:
            models.append(model)
        if isinstance(entry.get("effort"), str):
            effort = entry["effort"]
    return Reviewer(model=", ".join(models) if models else None, effort=effort)


def read_code_review_findings(path: Path) -> tuple[list[Any], Reviewer]:
    """Read the findings array a /code-review run reported, and the model and effort that ran it when recorded.

    The file holds either exactly that array, which records no model, or the transcript of the /code-review agent,
    whose last ```json block in an assistant message holds it.
    """
    text = path.read_text(encoding="utf-8")
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        # a .jsonl transcript has one JSON document per line, so it does not parse as a whole
        return _findings_array_from_transcript(text), _reviewer_from_transcript(text)
    if isinstance(whole, list):
        return whole, Reviewer(model=None, effort=None)
    return _findings_array_from_transcript(text), _reviewer_from_transcript(text)


def _existing_findings(*, owner: str, repo: str, pr: int) -> dict[str, PostedComment]:
    existing: dict[str, PostedComment] = {}
    for endpoint, is_review_comment in (
        (f"repos/{owner}/{repo}/pulls/{pr}/comments", True),
        (f"repos/{owner}/{repo}/issues/{pr}/comments", False),
    ):
        for c in gh_rest("api", endpoint, "--paginate"):
            # only a thread's root holds a finding; a reply may quote one
            if c.get("in_reply_to_id") is not None:
                continue
            finding = parse_ai_review_finding(c.get("body") or "")
            if finding is not None:
                existing[finding.finding_id] = PostedComment(
                    node_id=c["node_id"], url=c["html_url"], is_review_comment=is_review_comment
                )
    return existing


def _next_finding_number(existing_ids: set[str]) -> int:
    highest = 0
    for finding_id in existing_ids:
        match = _FINDING_NUMBER_RE.fullmatch(finding_id)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def build_plan(findings_file: FindingsFile) -> Plan:
    owner, repo = owner_repo_from_remote()
    data = gh_graphql(PR_QUERY, {"owner": owner, "repo": repo, "number": findings_file.pr})
    repository = data["repository"]
    pull_request = repository["pullRequest"]
    if pull_request["state"] != "OPEN":
        _fail(f"PR #{findings_file.pr} is {pull_request['state']}, not OPEN")
    viewer = data["viewer"]["login"]
    pending_review_ids = [
        r["id"] for r in pull_request["reviews"]["nodes"] if (r.get("author") or {}).get("login") == viewer
    ]

    head = _ensure_commit(pull_request["headRefOid"])
    base = _ensure_commit(pull_request["baseRefOid"])
    reviewed = _ensure_commit(findings_file.reviewed_commit)
    reviewed_in_pr = _is_ancestor(ancestor=reviewed, descendant=head) and not _is_ancestor(
        ancestor=reviewed, descendant=base
    )
    anchor = reviewed if reviewed_in_pr else head
    commentable = _commentable_lines(base=base, anchor=anchor)

    planned = [
        _plan_finding(finding=finding, reviewed=reviewed, anchor=anchor, head=head, commentable=commentable)
        for finding in findings_file.findings
    ]

    return Plan(
        pr_node_id=pull_request["id"],
        pr_head=head,
        pr_base=base,
        anchor_commit=anchor,
        reviewed_commit_in_pr=reviewed_in_pr,
        visibility=repository["visibility"],
        reviewer_model=findings_file.reviewer.model,
        pending_review_ids=pending_review_ids,
        existing_findings=_existing_findings(owner=owner, repo=repo, pr=findings_file.pr),
        planned=planned,
    )


def _plan_finding(
    *, finding: Finding, reviewed: str, anchor: str, head: str, commentable: dict[str, set[int]]
) -> PlannedFinding:
    in_diff = finding.file in commentable
    if not _file_exists_at(commit=anchor, path=finding.file):
        if in_diff:
            # deleted by the PR: only the left side of the diff has the line, so comment on the file
            return PlannedFinding(
                finding=finding, placement="file", line_at_anchor=None, changed_since_review=False, attention=None
            )
        return PlannedFinding(
            finding=finding,
            placement="pr_comment",
            line_at_anchor=None,
            changed_since_review=False,
            attention=f"{finding.file} does not exist at {anchor[:SHORT_SHA_LENGTH]}; fix the path or drop the finding",
        )
    if finding.line is None:
        placement = "file" if in_diff else "pr_comment"
        return PlannedFinding(
            finding=finding, placement=placement, line_at_anchor=None, changed_since_review=False, attention=None
        )

    source = _ensure_commit(finding.line_commit) if finding.line_commit is not None else reviewed
    line_at_anchor = map_line_between(path=finding.file, line=finding.line, from_commit=source, to_commit=anchor)
    if line_at_anchor is None:
        return PlannedFinding(
            finding=finding,
            placement="pr_comment",
            line_at_anchor=None,
            changed_since_review=False,
            attention=(
                f"{finding.file}:{finding.line} at {source[:SHORT_SHA_LENGTH]} was changed by "
                f"{anchor[:SHORT_SHA_LENGTH]}, so it cannot be mapped. Find the code at the anchor commit and set "
                f"`line` and `line_commit` to it, or drop the finding if it no longer applies."
            ),
        )

    changed_since_review = False
    if anchor != head:
        line_at_head = map_line_between(path=finding.file, line=line_at_anchor, from_commit=anchor, to_commit=head)
        changed_since_review = line_at_head is None
    if line_at_anchor in commentable.get(finding.file, set()):
        placement = "line"
    elif in_diff:
        placement = "file"
    else:
        placement = "pr_comment"
    return PlannedFinding(
        finding=finding,
        placement=placement,
        line_at_anchor=line_at_anchor,
        changed_since_review=changed_since_review,
        attention=None,
    )


def _plan_json(*, plan: Plan, findings_file: FindingsFile, resume: bool) -> dict[str, Any]:
    already_posted = plan.already_posted(resume=resume)
    return {
        "pr": findings_file.pr,
        "visibility": plan.visibility,
        "reviewed_commit": findings_file.reviewed_commit,
        "reviewed_commit_in_pr": plan.reviewed_commit_in_pr,
        "anchor_commit": plan.anchor_commit,
        "pr_head": plan.pr_head,
        "pr_base": plan.pr_base,
        "findings": [
            {
                "id": p.finding.finding_id,
                "file": p.finding.file,
                "line_in_findings_file": p.finding.line,
                "line_at_anchor": p.line_at_anchor,
                "placement": p.placement,
                "changed_since_review": p.changed_since_review,
                "related": [r.finding_id for r in p.finding.related],
                "already_posted": already_posted[p.finding.finding_id].url
                if p.finding.finding_id in already_posted
                else None,
                "attention": p.attention,
            }
            for p in plan.planned
        ],
        "will_edit_posted_findings": plan.earlier_findings_to_relink(resume=resume),
        "blocking_problems": plan.blocking_problems(resume=resume),
    }


def _escape_table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _table_summary(finding: Finding) -> str:
    text = finding.short_summary or finding.summary
    if len(text) > TABLE_SUMMARY_MAX_LENGTH:
        text = text[: TABLE_SUMMARY_MAX_LENGTH - 1].rstrip() + "…"
    return _escape_table_cell(text)


def _location(planned: PlannedFinding) -> str:
    line = planned.line_at_anchor if planned.line_at_anchor is not None else planned.finding.line
    if line is None:
        return f"`{planned.finding.file}`"
    return f"`{planned.finding.file}:{line}`"


def _reviewer_description(reviewer: Reviewer) -> str:
    return describe_model(model=reviewer.model, effort=reviewer.effort)


def _ai_review_banner(*, findings_file: FindingsFile, noun: str) -> str:
    """Return the line that opens every posted comment, so a reader knows from the first line it came from an AI.

    It names the model and effort level that ran the review and the commit it reviewed.
    """
    return (
        f"> 🤖 **{noun}** by {_reviewer_description(findings_file.reviewer)}, reviewing "
        f"`{findings_file.reviewed_commit[:SHORT_SHA_LENGTH]}`"
    )


def render_finding_body(*, planned: PlannedFinding, urls: dict[str, str], findings_file: FindingsFile) -> str:
    finding = planned.finding
    heading = " · ".join(part for part in (f"**{finding.finding_id}**", finding.category) if part)
    lines = [
        ai_review_finding_marker(finding_id=finding.finding_id, related_ids=[r.finding_id for r in finding.related]),
        _ai_review_banner(findings_file=findings_file, noun="AI code review finding"),
        "",
        heading,
        "",
    ]
    if planned.placement == "pr_comment":
        lines += [f"**Location:** {_location(planned)} (not part of this PR's diff, so posted as a PR comment)", ""]
    elif planned.placement == "file" and planned.line_at_anchor is not None:
        lines += [f"**Location:** {_location(planned)} (outside this PR's diff hunks)", ""]
    lines += [finding.summary, "", f"**Failure scenario:** {finding.failure_scenario}", ""]
    if finding.related:
        lines.append("**Related:**")
        for related in finding.related:
            url = urls.get(related.finding_id)
            reference = f"[{related.finding_id}]({url})" if url is not None else related.finding_id
            lines.append(f"- {reference}: {related.note}")
        lines.append("")
    lines.append(POSTED_UNDER_NOTE)
    return "\n".join(lines)


def render_review_body(
    *, planned: list[PlannedFinding], findings_file: FindingsFile, urls: dict[str, str], continued: bool
) -> str:
    banner = _ai_review_banner(findings_file=findings_file, noun="AI code review")
    if continued:
        # the earlier review already carries the summary, so this one only lists what it adds
        lines = ["## AI code review findings (continued)", "", banner, ""]
    else:
        lines = ["## AI code review findings", "", banner, ""]
        if findings_file.summary:
            lines += [findings_file.summary, ""]
    lines += ["| ID | Location | Finding |", "|---|---|---|"]
    for p in planned:
        url = urls.get(p.finding.finding_id)
        reference = f"[{p.finding.finding_id}]({url})" if url is not None else p.finding.finding_id
        lines.append(f"| {reference} | {_escape_table_cell(_location(p))} | {_table_summary(p.finding)} |")
    lines += ["", POSTED_UNDER_NOTE]
    return "\n".join(lines)


def _first_comment(result: dict[str, Any]) -> dict[str, Any]:
    return result["addPullRequestReviewThread"]["thread"]["comments"]["nodes"][0]


def _review_state(review_id: str) -> dict[str, str] | None:
    try:
        review = gh_graphql(REVIEW_STATE, {"id": review_id})["node"]
    except subprocess.CalledProcessError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except RuntimeError:
        return None
    if not isinstance(review, dict):
        return None
    return {"state": str(review.get("state")), "url": str(review.get("url"))}


def _clean_up(*, review_id: str | None, posted: dict[str, PostedComment]) -> None:
    leftovers: list[tuple[str, str, dict[str, str | int | bool]]] = [
        (entry.url, DELETE_PR_COMMENT, {"id": entry.node_id})
        for entry in posted.values()
        if not entry.is_review_comment
    ]
    if review_id is not None:
        leftovers.append((f"pending review {review_id}", DELETE_REVIEW, {"reviewId": review_id}))
    for description, mutation, variables in leftovers:
        try:
            _ = gh_graphql(mutation, variables)
        except subprocess.CalledProcessError as e:
            _ = sys.stderr.write(f"Could not delete {description}; remove it by hand: {e.stderr}\n")
        except subprocess.TimeoutExpired:
            _ = sys.stderr.write(
                f"Could not delete {description} (timed out after {GH_TIMEOUT_SECONDS}s); remove it by hand.\n"
            )
        except RuntimeError as e:
            _ = sys.stderr.write(f"Could not delete {description}; remove it by hand: {e}\n")


def _urls(*comment_sets: dict[str, PostedComment]) -> dict[str, str]:
    return {finding_id: c.url for comments in comment_sets for finding_id, c in comments.items()}


def _add_thread(*, review_id: str, planned: PlannedFinding, body: str) -> PostedComment:
    if planned.placement == "line" and planned.line_at_anchor is not None:
        variables: dict[str, str | int | bool] = {
            "reviewId": review_id,
            "path": planned.finding.file,
            "line": planned.line_at_anchor,
            "body": body,
        }
        comment = _first_comment(gh_graphql(ADD_LINE_THREAD, variables))
    else:
        comment = _first_comment(
            gh_graphql(ADD_FILE_THREAD, {"reviewId": review_id, "path": planned.finding.file, "body": body})
        )
    return PostedComment(node_id=comment["id"], url=comment["url"], is_review_comment=True)


def _relink(
    *,
    plan: Plan,
    findings_file: FindingsFile,
    posted: dict[str, PostedComment],
    already_posted: dict[str, PostedComment],
) -> None:
    """Fill in the links to the findings this post added, now that their URLs exist.

    Every finding related to one added now is edited, whether it was added now too or by an earlier post (which is
    what plan reports as will_edit_posted_findings). Links to earlier findings were already in each new comment's
    first body, so a finding related only to those is left alone.
    """
    comments = {**already_posted, **posted}
    urls = _urls(comments)
    for p in plan.planned:
        if not {r.finding_id for r in p.finding.related} & posted.keys():
            continue
        entry = comments[p.finding.finding_id]
        body = render_finding_body(planned=p, urls=urls, findings_file=findings_file)
        mutation = UPDATE_REVIEW_COMMENT if entry.is_review_comment else UPDATE_PR_COMMENT
        _ = gh_graphql(mutation, {"id": entry.node_id, "body": body})


def _settle_failed_post(*, review_id: str | None, posted: dict[str, PostedComment]) -> str | None:
    """Clean up after an error while posting, unless the review turns out to have been submitted.

    An error does not mean the review is still pending: GitHub can apply a submit and still return an empty response.
    Deleting the PR comments of a submitted review would leave its findings linking to nothing. Returns the review's
    URL when it was submitted (the post succeeded), else None once whatever can be removed has been.
    """
    if review_id is None:
        _ = sys.stderr.write("Posting failed; deleting the PR comments it created.\n")
        _clean_up(review_id=None, posted=posted)
        return None
    review = _review_state(review_id)
    if review is None:
        _ = sys.stderr.write(
            f"Posting failed and the state of review {review_id} could not be read, so nothing was deleted. "
            "Check the PR, then run post again with --resume to post only what is missing.\n"
        )
        return None
    if review["state"] == "PENDING":
        _ = sys.stderr.write("Posting failed; deleting the pending review and any PR comments it created.\n")
        _clean_up(review_id=review_id, posted=posted)
        return None
    _ = sys.stderr.write("The submit's response was lost, but GitHub shows the review as submitted.\n")
    return review["url"]


def _post(*, plan: Plan, findings_file: FindingsFile, resume: bool) -> dict[str, Any]:
    already_posted = plan.already_posted(resume=resume)
    to_post = [p for p in plan.planned if p.finding.finding_id not in already_posted]
    threads = [p for p in to_post if p.placement != "pr_comment"]
    review_id: str | None = None
    if to_post:
        review_id = gh_graphql(ADD_REVIEW, {"pullRequestId": plan.pr_node_id, "commitOID": plan.anchor_commit})[
            "addPullRequestReview"
        ]["pullRequestReview"]["id"]
    posted: dict[str, PostedComment] = {}
    review_url: str | None = None
    try:
        if review_id is not None:
            for p in threads:
                body = render_finding_body(planned=p, urls=_urls(already_posted), findings_file=findings_file)
                posted[p.finding.finding_id] = _add_thread(review_id=review_id, planned=p, body=body)

        for p in to_post:
            if p.placement != "pr_comment":
                continue
            body = render_finding_body(planned=p, urls=_urls(already_posted, posted), findings_file=findings_file)
            node = gh_graphql(ADD_PR_COMMENT, {"subjectId": plan.pr_node_id, "body": body})["addComment"][
                "commentEdge"
            ]["node"]
            posted[p.finding.finding_id] = PostedComment(node_id=node["id"], url=node["url"], is_review_comment=False)

        urls = _urls(already_posted, posted)
        _relink(plan=plan, findings_file=findings_file, posted=posted, already_posted=already_posted)

        if review_id is not None:
            review_body = render_review_body(
                planned=to_post, findings_file=findings_file, urls=urls, continued=bool(already_posted)
            )
            review_url = gh_graphql(SUBMIT_REVIEW, {"reviewId": review_id, "body": review_body})[
                "submitPullRequestReview"
            ]["pullRequestReview"]["url"]
    except BaseException:
        submitted_url = _settle_failed_post(review_id=review_id, posted=posted)
        if submitted_url is None:
            raise
        review_url = submitted_url
    return {
        "review_url": review_url,
        "anchor_commit": plan.anchor_commit,
        "findings": _urls(already_posted, posted),
    }


def cmd_import(args: argparse.Namespace) -> None:
    raw_findings, recorded_reviewer = read_code_review_findings(args.source)
    reviewer = Reviewer(
        model=args.model if args.model is not None else recorded_reviewer.model,
        effort=args.effort if args.effort is not None else recorded_reviewer.effort,
    )
    owner, repo = owner_repo_from_remote()
    next_number = _next_finding_number(set(_existing_findings(owner=owner, repo=repo, pr=args.pr)))
    findings = [
        _parse_finding(
            raw={**raw, "related": []} if isinstance(raw, dict) else raw, finding_id=f"F{next_number + i}", index=i
        )
        for i, raw in enumerate(raw_findings)
    ]
    findings_file = FindingsFile(
        pr=args.pr,
        reviewed_commit=_ensure_commit(args.commit),
        reviewer=reviewer,
        summary="",
        findings=findings,
        posted=None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _write_findings_file(path=args.out, findings_file=findings_file)
    _ = sys.stdout.write(
        f"Wrote {len(findings)} findings ({findings[0].finding_id if findings else '-'} onwards) to {args.out}, "
        f"reviewed by {_reviewer_description(reviewer)}\n"
    )


def render_preview(*, plan: Plan, findings_file: FindingsFile, resume: bool) -> str:
    already_posted = plan.already_posted(resume=resume)
    to_post = [p for p in plan.planned if p.finding.finding_id not in already_posted]
    # findings not yet posted have no URL, so the preview points each one at its own heading instead
    urls = {**{p.finding.finding_id: f"#{p.finding.finding_id.lower()}" for p in to_post}, **_urls(already_posted)}
    sections = [
        f"# Preview of the review for PR #{findings_file.pr}",
        f"Anchored to `{plan.anchor_commit[:SHORT_SHA_LENGTH]}`. Nothing here has been posted.",
    ]
    if already_posted:
        sections.append(f"Already on the PR, so skipped: {', '.join(already_posted)}.")
        relinked = plan.earlier_findings_to_relink(resume=resume)
        if relinked:
            sections.append(f"Edited to link the new findings (GitHub marks them edited): {', '.join(relinked)}.")
            # an edit to a comment already on the PR goes out too, so its new body is shown like a new one
            for p in plan.planned:
                if p.finding.finding_id not in relinked:
                    continue
                sections += [
                    f"---\n\n# {p.finding.finding_id} (already posted; edited to this)",
                    render_finding_body(planned=p, urls=urls, findings_file=findings_file),
                ]
    if to_post:
        sections += [
            "---\n\n# Review body",
            render_review_body(planned=to_post, findings_file=findings_file, urls=urls, continued=bool(already_posted)),
        ]
    for p in to_post:
        where = _location(p) if p.placement == "pr_comment" else f"{p.placement} comment on {_location(p)}"
        sections += [
            f"---\n\n# {p.finding.finding_id}\n\n_{where}_",
            render_finding_body(planned=p, urls=urls, findings_file=findings_file),
        ]
    return "\n\n".join(sections) + "\n"


def cmd_plan(args: argparse.Namespace) -> None:
    findings_file = load_findings_file(args.findings_file)
    plan = build_plan(findings_file)
    if args.preview is not None:
        preview = render_preview(plan=plan, findings_file=findings_file, resume=args.resume)
        _ = args.preview.write_text(preview, encoding="utf-8")
    _ = sys.stdout.write(
        json.dumps(_plan_json(plan=plan, findings_file=findings_file, resume=args.resume), indent=2) + "\n"
    )


def cmd_post(args: argparse.Namespace) -> None:
    findings_file = load_findings_file(args.findings_file)
    if findings_file.posted is not None:
        _fail(f"{args.findings_file} was already posted: {findings_file.posted.get('review_url')}")
    plan = build_plan(findings_file)
    if plan.pr_head != args.head:
        _fail(
            f"Not posting; the PR head is now {plan.pr_head}, not the approved {args.head}: the PR changed since "
            "approval, so the preview may no longer match what would be posted. Run `plan` again and get a new "
            "approval."
        )
    if plan.pr_base != args.base:
        _fail(
            f"Not posting; the PR base is now {plan.pr_base}, not the approved {args.base}: a moved base changes which "
            "lines are in the diff, so where a finding would be posted. Run `plan` again and get a new approval."
        )
    problems = plan.blocking_problems(resume=args.resume)
    if problems:
        _fail("Not posting; resolve these first (see `plan`):\n- " + "\n- ".join(problems))
    already_posted = plan.already_posted(resume=args.resume)
    if not [p for p in plan.planned if p.finding.finding_id not in already_posted]:
        # no review would be created, so recording the file as posted would only block a real post of it later
        _fail(
            "Not posting; no finding in the file is left to post, so there would be no review. "
            "Add findings, or, after a --resume, check `plan`: every finding is already on the PR."
        )
    findings_file.posted = _post(plan=plan, findings_file=findings_file, resume=args.resume)
    _write_findings_file(path=args.findings_file, findings_file=findings_file)
    _ = sys.stdout.write(json.dumps(findings_file.posted, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="convert /code-review output into a findings file")
    _ = import_parser.add_argument("--from", dest="source", required=True, type=Path)
    _ = import_parser.add_argument("--pr", required=True, type=int)
    _ = import_parser.add_argument("--commit", required=True, help="the commit the review was run against")
    _ = import_parser.add_argument("--out", required=True, type=Path)
    _ = import_parser.add_argument(
        "--model", default=None, help="the model ID that ran the review; overrides what a transcript records"
    )
    _ = import_parser.add_argument(
        "--effort", default=None, help="the effort level the review ran at; overrides what a transcript records"
    )
    import_parser.set_defaults(handler=cmd_import)

    plan_parser = subparsers.add_parser("plan", help="show where each finding would be posted, posting nothing")
    _ = plan_parser.add_argument("--findings-file", required=True, type=Path)
    _ = plan_parser.add_argument(
        "--preview", type=Path, default=None, help="also write the review and every comment as they would be posted"
    )
    plan_parser.set_defaults(handler=cmd_plan)

    post_parser = subparsers.add_parser("post", help="post the findings as one review")
    _ = post_parser.add_argument("--findings-file", required=True, type=Path)
    _ = post_parser.add_argument(
        "--head",
        required=True,
        help="the pr_head of the plan the user approved; posting stops if the PR has moved since",
    )
    _ = post_parser.add_argument(
        "--base",
        required=True,
        help="the pr_base of the plan the user approved; posting stops if the PR's base has moved since",
    )
    for sub in (plan_parser, post_parser):
        _ = sub.add_argument(
            "--resume",
            action="store_true",
            help="skip findings whose IDs are already on the PR (from a post that did not finish) and post the rest",
        )
    post_parser.set_defaults(handler=cmd_post)

    args = parser.parse_args()
    try:
        args.handler(args)
    except InputError as e:
        _fail(f"Invalid input: {e}")
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON: {e}")
    except OSError as e:
        _fail(f"File error: {e}")
    except subprocess.CalledProcessError as e:
        _fail(f"gh api error: {e.stderr}")
    except subprocess.TimeoutExpired:
        _fail(f"gh api timed out after {GH_TIMEOUT_SECONDS}s")
    except RuntimeError as e:
        _fail(str(e))


if __name__ == "__main__":
    main()
