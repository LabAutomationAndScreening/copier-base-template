"""Shared comment-audit logic: the single source of truth for what counts as an added comment.

Both the gate (comment-gate.py, run as the PreToolUse hook) and the agent-facing tool
(comment-audit.py list/stamp) import from here, so the set the skill reviews is exactly the set the
gate blocks — same range resolution, same per-file-type comment syntax, same multi-line coalescing.
"""

# A skill is copied into a project whole, so it cannot import a helper from a sibling skill; run_cmd
# matching address-pr-comments' copy is the cost of that self-containment.
# pylint: disable=duplicate-code

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_PYTHON_RE = re.compile(r"\.py$")

MARKER_NAME = ".comment-audit-ok"

# Only py/yaml/toml/sh/rb treat a leading `#` as a comment; in JS/TS/Vue `#` is a private field, a hex
# colour, or an id selector, and markdown's only comment syntax is <!-- -->.
_HASH_COMMENT_RE = re.compile(r"\.(py|ya?ml|toml|sh|rb)$")
_MARKDOWN_RE = re.compile(r"\.(md|markdown)$")

# The command's git subcommand is `push`: anchored after any leading env assignments and git's global
# options, so neither a path containing "push" nor a commit message mentioning "git push" trips the gate.
_GIT_PUSH_RE = re.compile(r"^(?:\w+=\S*\s+)*git\s+(?:-\S+\s+)*push(?:\s|$)")
_PUSH_HELP_RE = re.compile(r"\bpush\b[^\n]*(-h\b|--help\b)")


def run_cmd(
    cmd: list[str],
    *,
    timeout: int,
    timeout_msg: str,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — callers only pass fixed git argv lists
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        _ = sys.stderr.write(f"{timeout_msg}\n")
        sys.exit(1)


def git(args: list[str], cwd: str) -> str:
    """Run a git command in cwd and return its trimmed stdout. Raises CalledProcessError on failure."""
    result = run_cmd(
        ["git", *args],
        timeout=30,
        timeout_msg=f"git {' '.join(args)} timed out.",
        cwd=cwd,
    )
    return result.stdout.strip()


def is_git_push(cmd: str) -> bool:
    return bool(_GIT_PUSH_RE.search(cmd)) and not _PUSH_HELP_RE.search(cmd)


def scan_comment(line: str, file: str) -> str | None:
    """Return the comment line exactly as authored (trimmed), or None if it is not a comment.

    Does not judge quality — that is the skill's job. Suppression directives (eslint-disable, @ts-*,
    prettier-ignore, ...) are returned too, on purpose: the project requires a why on every ignore/skip,
    so the audit must see them rather than wave them through.
    """
    raw = line.strip()
    prose: str | None = None
    if _MARKDOWN_RE.search(file):
        # Markdown's only comment syntax is <!-- -->.
        if raw.startswith("<!--"):
            prose = raw[4:].removesuffix("-->").strip()
    elif _HASH_COMMENT_RE.search(file):
        # py/yaml/toml/sh/rb: only a leading `#` is a comment. Crucially, C-style rules must NOT apply
        # here — a leading `*` is `*args`/`*,` and `//` is a floor-division operator, not a comment.
        if raw.startswith("#") and not raw.startswith("#!"):
            prose = raw[1:].strip()
    elif raw.startswith("//"):
        prose = raw[2:].strip()
    elif raw.startswith("/*"):
        prose = raw[2:].removesuffix("*/").strip()
    elif raw.startswith("*") and not raw.startswith("*/"):
        prose = raw[1:].strip()
    elif raw.startswith("<!--"):
        prose = raw[4:].removesuffix("-->").strip()
    if not prose:
        return None
    return raw


def _flush(groups: list[dict[str, Any]], cur: dict[str, Any] | None) -> None:
    """Append the open comment run, if any, to the finished groups."""
    if cur:
        groups.append(cur)


def _consume_added(
    groups: list[dict[str, Any]],
    cur: dict[str, Any] | None,
    file: str,
    new_line: int,
    comment: str | None,
) -> dict[str, Any] | None:
    """Fold one added line into the open run: extend it if adjacent, else start a new run.

    A non-comment added line breaks the run and returns None.
    """
    if not comment:
        _flush(groups, cur)
        return None
    if cur and cur["file"] == file and new_line == cur["end"] + 1:
        cur["end"] = new_line
        cur["raws"].append(comment)
        return cur
    _flush(groups, cur)
    return {"file": file, "start": new_line, "end": new_line, "raws": [comment], "kind": "comment"}


def added_comments(diff: str) -> list[dict[str, Any]]:
    """Return one entry per *logical* comment.

    Consecutive added comment lines in the same file are coalesced, so a multi-line comment is shown whole
    (with a line range), not as scattered fragments.
    """
    groups: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    file = ""
    new_line = 0

    for raw in diff.split("\n"):
        if raw.startswith("+++ b/"):
            file = raw[6:].strip()
            _flush(groups, cur)
            cur = None
            continue
        if raw.startswith(("+++", "---")):
            continue
        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if hunk:
            new_line = int(hunk.group(1))
            _flush(groups, cur)
            cur = None
            continue
        if raw.startswith("-"):
            continue  # removed line: no source line to advance past
        if raw.startswith("+"):
            cur = _consume_added(groups, cur, file, new_line, scan_comment(raw[1:], file))
        else:
            _flush(groups, cur)  # context line breaks the run
            cur = None
        new_line += 1

    _flush(groups, cur)
    return groups


def _own_upstream_ref(cwd: str) -> str | None:
    """Return the full refname of HEAD's own remote-tracking branch (refs/remotes/origin/foo), or None."""
    try:
        return git(["rev-parse", "--symbolic-full-name", "@{u}"], cwd)
    except subprocess.CalledProcessError:
        return None


def _closest_remote_base(cwd: str, *, exclude: str | None) -> str | None:
    """Merge-base with the remote-tracking branch whose fork point sits closest to HEAD.

    `exclude` drops one refname from consideration (HEAD's own remote-tracking branch, whose merge-base is
    HEAD itself and would audit nothing). Returns None when no remote ref is related to HEAD.
    """
    refs = [r for r in git(["for-each-ref", "--format=%(refname)", "refs/remotes"], cwd).split("\n") if r]
    best: str | None = None
    best_dist = float("inf")
    for ref in refs:
        if ref == exclude:
            continue
        try:
            merge_base = git(["merge-base", "HEAD", ref], cwd)
            dist = int(git(["rev-list", "--count", f"{merge_base}..HEAD"], cwd))
        except subprocess.CalledProcessError:
            continue  # ref unrelated to HEAD
        if dist < best_dist:
            best_dist = dist
            best = merge_base
    return best


def resolve_base(cwd: str, *, manual: bool = False) -> str:
    """Resolve the range base to audit against.

    COMMENT_GATE_BASE overrides both modes (tests).

    Hook mode (manual=False, the gate): the upstream's merge-base, so a push audits only the commits it
    actually adds. For a branch with no upstream, base on the remote-tracking branch whose merge-base sits
    closest to HEAD. Fall back to origin/main.

    Manual mode (manual=True, /comment-audit): audit the whole branch against the branch it was forked from.
    A fully-pushed branch's own upstream is HEAD, so diffing against it finds nothing — instead skip the
    upstream and base on the closest OTHER remote-tracking branch's fork point, falling back to origin/main.
    """
    override = os.environ.get("COMMENT_GATE_BASE")
    if override:
        return override
    if manual:
        base = _closest_remote_base(cwd, exclude=_own_upstream_ref(cwd))
        return base or git(["merge-base", "HEAD", "origin/main"], cwd)
    try:
        return git(["merge-base", "HEAD", "@{u}"], cwd)
    except subprocess.CalledProcessError:
        pass  # no upstream
    base = _closest_remote_base(cwd, exclude=None)
    return base or git(["merge-base", "HEAD", "origin/main"], cwd)


def added_line_map(diff: str) -> dict[str, set[int]]:
    """Map each file to the set of source line numbers added in the diff."""
    added: dict[str, set[int]] = {}
    file = ""
    new_line = 0
    for raw in diff.split("\n"):
        if raw.startswith("+++ b/"):
            file = raw[6:].strip()
            continue
        if raw.startswith(("+++", "---")):
            continue
        hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if raw.startswith("-"):
            continue
        if raw.startswith("+"):
            added.setdefault(file, set()).add(new_line)
        new_line += 1
    return added


def python_docstrings(source: str, file: str, added_lines: set[int]) -> list[dict[str, Any]]:
    """Return each module/class/function docstring whose line span intersects added_lines.

    Uses the AST, not line scanning: a docstring is a multi-line string literal and a diff hunk can begin
    inside one, so only the parse tree reliably delimits it. Reported like a comment (file/start/end/raws)
    but tagged kind="docstring" so the audit can hold it to a docstring-appropriate bar.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.split("\n")
    entries: list[dict[str, Any]] = []
    doc_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, doc_owners) or ast.get_docstring(node) is None:
            continue
        expr = node.body[0]  # get_docstring guarantees the first statement is the docstring expression
        start = expr.lineno
        end = expr.end_lineno or start
        if added_lines.isdisjoint(range(start, end + 1)):
            continue
        entries.append({"file": file, "start": start, "end": end, "raws": lines[start - 1 : end], "kind": "docstring"})
    return entries


def collect_added_comments(cwd: str, *, manual: bool = False) -> dict[str, Any]:
    """Collect the audited base, HEAD, git dir, and every added comment and docstring in that range.

    manual=True audits the whole branch against its fork point (see resolve_base); the default hook path
    audits only the outgoing (not-yet-pushed) commits.
    """
    head = git(["rev-parse", "HEAD"], cwd)
    git_dir = git(["rev-parse", "--absolute-git-dir"], cwd)
    base = resolve_base(cwd, manual=manual)
    diff = git(["diff", f"{base}..{head}", "--unified=0", "--no-color"], cwd)

    entries = added_comments(diff)
    for path, added in added_line_map(diff).items():
        if not _PYTHON_RE.search(path):
            continue
        try:
            # Read the blob unstripped so line numbers stay true (git() strips, which would shift them).
            source = run_cmd(
                ["git", "show", f"{head}:{path}"],
                timeout=30,
                timeout_msg=f"git show {path} timed out.",
                cwd=cwd,
            ).stdout
        except subprocess.CalledProcessError:
            continue  # blob unreadable (deleted at HEAD, binary, ...)
        entries.extend(python_docstrings(source, path, added))

    entries.sort(key=lambda e: (e["file"], e["start"]))
    return {"base": base, "head": head, "gitDir": git_dir, "comments": entries}


def _blob_lines(cwd: str, head: str, path: str) -> list[str] | None:
    try:
        source = run_cmd(
            ["git", "show", f"{head}:{path}"],
            timeout=30,
            timeout_msg=f"git show {path} timed out.",
            cwd=cwd,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return source.split("\n")


def _context_block(lines: list[str], entry: dict[str, Any], *, before: int, after: int) -> str:
    start, end = entry["start"], entry["end"]
    lo = max(1, start - before)
    hi = min(len(lines), end + after)
    out = [f"{entry['file']}:{start}-{end}  [{entry['kind']}]"]
    for ln in range(lo, hi + 1):
        # Mark the comment/docstring lines themselves so the surrounding code reads as context.
        flag = ">" if start <= ln <= end else " "
        out.append(f"  {flag}{ln:>5}  {lines[ln - 1]}")
    return "\n".join(out)


def collect_for_review(cwd: str, *, manual: bool = True) -> dict[str, Any]:
    """collect_added_comments plus a verbatim, line-numbered `block` on each comment for the Step 3 review.

    A superset of the bare detection: every entry gains a `block` pulled straight from the HEAD blob, so
    the audit never hand-transcribes a comment. A docstring's block is quoted with the def/class owner line
    above it and a little body below; an inline comment's with the code below it — each shown against the
    code it is actually judged against.
    """
    data = collect_added_comments(cwd, manual=manual)
    head = data["head"]
    blobs: dict[str, list[str] | None] = {}
    for entry in data["comments"]:
        path = entry["file"]
        if path not in blobs:
            blobs[path] = _blob_lines(cwd, head, path)
        lines = blobs[path]
        if lines is None:
            entry["block"] = f"{path}:{entry['start']}-{entry['end']}  [blob unreadable]"
            continue
        before, after = (3, 2) if entry["kind"] == "docstring" else (0, 5)
        entry["block"] = _context_block(lines, entry, before=before, after=after)
    return data


def stamp_approval(cwd: str) -> tuple[str, Path]:
    """Record HEAD in the approval marker, using the same git dir the gate reads."""
    head = git(["rev-parse", "HEAD"], cwd)
    git_dir = git(["rev-parse", "--absolute-git-dir"], cwd)
    marker = Path(git_dir) / MARKER_NAME
    _ = marker.write_text(head + "\n", encoding="utf-8")
    return head, marker
