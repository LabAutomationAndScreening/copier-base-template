#!/usr/bin/env python3
"""Comment-audit detection, its PreToolUse hook, and the agent-facing CLI.

Three verbs:

  comment-audit.py gate             Run as the Claude Code PreToolUse hook. Reads the hook payload as
                                        JSON on stdin. Exit 0 allows the push; exit 2 blocks it. In
                                        `warn` the report is emitted as hook JSON on stdout, because
                                        PreToolUse plain stdout only reaches the debug log.

  comment-audit.py list  <repo-root>  Print the audited comments as JSON: {base, head, gitDir, comments:
                                        [{file, start, end, raws, kind, block}]}.

  comment-audit.py stamp <repo-root>  Record HEAD in <git-dir>/.comment-audit-ok so the gate lets the
                                        next push through. Run AFTER the final commit — the marker must
                                        match HEAD, and the gate consumes it (single-use) on that push.

Why: when addressing PR review comments the agent tends to leave behind source comments that either
restate what the code does (WHAT-comments) or are really the reply to the reviewer. Those should be
removed; only comments explaining a non-obvious WHY earn their place. The gate is the tripwire — it does
NOT judge the comments itself. It detects that the outgoing push adds source comments and, unless they
have been audited, says so and points at the `comment-audit` skill.

Division of labour:
  - gate  (this file): deterministic detection + attestation check. Cheap, no LLM.
  - skill (comment-audit): the actual review — classify each comment, review every one with the human
    (keep/drop/edit), apply decisions, then stamp the attestation marker.

One file on purpose: the gate and the `list` verb must agree exactly on what counts as an added comment,
and sharing a module makes that structural rather than something a docstring has to promise. It also
leaves a skill one file to vendor and one file to mark executable.

The mode is `mode` in <project>/.config/claude/comment-audit.toml. Anything missing, unreadable or
unrecognised means `off`: the gate is opt-in, so a project that has not asked for it — or whose config
cannot be read — gets silence rather than a hook that starts talking on its own.

`warn` is the mode to start with when a project does opt in: the detector's precision on a given repo is
unknown until it has run against real branches, and a false positive in `warn` is noise where in `block`
it is a work stoppage. Move a project to `block` once warn-mode reports have proven trustworthy.

Scope: the hook only intercepts the AGENT's `git push`. A human running `git push` directly is never
affected — that, or the skill's attestation, is the only way past `block`. There is deliberately no
agent-settable override: an env flag the agent could add itself would be no gate. Only HEAD is audited, so
only a plain push of the current branch is recognised; any other push (`other:main`, `--all`, `:stale`,
`-o ...`) is treated like one whose range could not be determined: blocked in `block`, reported in `warn`.

Attestation: the skill writes <git-dir>/.comment-audit-ok containing the HEAD sha it reviewed. A marker
matching the current HEAD silences the gate (and is then consumed) in every mode, so `warn` and `block`
agree on what counts as audited. This stops the accidental/forgetful bypass; it is not proof against an
adversarial agent (a file is a file).
"""

import ast
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import NoReturn

MARKER_NAME = ".comment-audit-ok"

# Only py/yaml/toml/sh/rb treat a leading `#` as a comment; in JS/TS/Vue `#` is a private field, a hex
# colour, or an id selector, and markdown's only comment syntax is <!-- -->.
_HASH_COMMENT_RE = re.compile(r"\.(py|ya?ml|toml|sh|rb)$")
_MARKDOWN_RE = re.compile(r"\.(md|markdown)$")

_ENV_ASSIGNMENT_RE = re.compile(r"^\w+=")
# Global options whose value is the NEXT token; the `--opt=value` spelling is a single token and needs no
# entry. Missing one here means its value is mistaken for the subcommand and the push goes ungated.
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})
# --git-dir/--work-tree point git at a repo the gate's own git calls (run in cwd) would not see.
_GIT_REPO_OPTIONS = frozenset({"--git-dir", "--work-tree"})
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", "&"})
# `git push` flags that change how the current branch is pushed but never which refs go. None takes a
# separate value token, so nothing here can hide a refspec from the allowlist.
_PUSH_ALLOWED_FLAGS = frozenset(
    {"-u", "--set-upstream", "-f", "--force", "--force-with-lease", "--force-if-includes", "--no-verify"}
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

MODE_OFF = "off"
MODE_WARN = "warn"
MODE_BLOCK = "block"
_MODES = frozenset({MODE_OFF, MODE_WARN, MODE_BLOCK})
CONFIG_RELPATH = Path(".config") / "claude" / "comment-audit.toml"

VERB_AND_ROOT_ARGC = 2
GIT_TIMEOUT_SECONDS = 30

_GUIDANCE = (
    "Run the comment-audit skill — invoke /comment-audit. It reviews every comment with you\n"
    "(why-not-what; drops what-restatements, reply text, and historical narration), applies your\n"
    "keep/drop/edit decisions and stamps approval."
)


def git(args: list[str], cwd: str, *, strip: bool = True) -> str:
    """Run a git command in cwd, raising CalledProcessError or TimeoutExpired on failure.

    Pass strip=False when reading a blob: trimming leading blank lines would shift its line numbers.
    """
    stdout = subprocess.run(  # noqa: S603 — callers only pass fixed git argv lists
        ["git", *args],  # noqa: S607 — git is resolved from PATH
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
        cwd=cwd,
    ).stdout
    return stdout.strip() if strip else stdout


@dataclass(frozen=True)
class PushInvocation:
    args: list[str]  # tokens after `push`, up to the first shell operator
    chdirs: list[str]  # each -C value, in order; git applies them cumulatively
    repo_override: bool  # --git-dir/--work-tree given


def parse_push(cmd: str) -> PushInvocation | None:
    """Return the push this command runs, or None if its git subcommand is not `push`.

    Tokenised rather than pattern-matched so that global options are consumed with their values: neither
    a path containing "push" nor a commit message mentioning "git push" trips the gate, and `git -C <path>
    push` does not slip past it.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return None  # unbalanced quoting: the shell will reject it before git runs
    i = 0
    while i < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[i]):
        i += 1
    if i >= len(tokens) or tokens[i] != "git":
        return None
    globals_end = _consume_git_globals(tokens, i + 1)
    if globals_end is None:
        return None
    i, chdirs, repo_override = globals_end
    if i >= len(tokens) or tokens[i] != "push":
        return None
    args: list[str] = []
    for tok in tokens[i + 1 :]:
        if tok in _SHELL_OPERATORS:
            break
        args.append(tok)
    if "-h" in args or "--help" in args:
        return None  # prints usage; pushes nothing
    return PushInvocation(args=args, chdirs=chdirs, repo_override=repo_override)


def _consume_git_globals(tokens: list[str], i: int) -> tuple[int, list[str], bool] | None:
    """Step past git's global options from tokens[i]; return (subcommand index, -C values, repo override)."""
    chdirs: list[str] = []
    repo_override = False
    while i < len(tokens) and tokens[i].startswith("-"):
        repo_override = repo_override or tokens[i].split("=", 1)[0] in _GIT_REPO_OPTIONS
        if tokens[i] in _GIT_VALUE_OPTIONS:
            if i + 1 >= len(tokens):
                return None
            if tokens[i] == "-C":
                chdirs.append(tokens[i + 1])
            i += 1
        i += 1
    return i, chdirs, repo_override


def scan_comment(line: str, file: str) -> str | None:
    """Return the comment line exactly as authored (trimmed), or None if it is not a comment.

    Does not judge quality — that is the skill's job. Suppression directives (eslint-disable, @ts-*,
    prettier-ignore, ...) are returned too, on purpose: the project requires a why on every ignore/skip,
    so the audit must see them rather than wave them through.
    """
    raw = line.strip()
    prose: str | None = None
    if _MARKDOWN_RE.search(file):
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


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    r"""Yield (file, line number at HEAD, text) for every line a unified diff adds.

    `+++`/`---` are only file headers before a file's first hunk; inside a hunk they are an added `++x` or
    a removed `--x`. `\ No newline at end of file` is a marker, not a source line.
    """
    file = ""
    new_line = 0
    in_hunk = False
    for raw in diff.split("\n"):
        hunk = _HUNK_RE.match(raw)
        if raw.startswith("diff --git "):
            in_hunk = False
        elif hunk:
            new_line = int(hunk.group(1))
            in_hunk = True
        elif not in_hunk:
            if raw.startswith("+++ b/"):
                file = raw[6:].strip()
        elif raw.startswith("+"):
            yield file, new_line, raw[1:]
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1


def added_comments(lines: Iterable[tuple[str, int, str]]) -> list[dict[str, Any]]:
    """Return one entry per *logical* comment.

    Added comment lines on consecutive lines of the same file are coalesced, so a multi-line comment is
    shown whole (with a line range), not as scattered fragments.
    """
    groups: list[dict[str, Any]] = []
    for file, line, text in lines:
        comment = scan_comment(text, file)
        if comment is None:
            continue
        last = groups[-1] if groups else None
        if last and last["file"] == file and last["end"] == line - 1:
            last["end"] = line
            last["raws"].append(comment)
        else:
            groups.append({"file": file, "start": line, "end": line, "raws": [comment], "kind": "comment"})
    return groups


def _closest_remote_base(cwd: str, *, exclude: str | None) -> str | None:
    """Merge-base with the remote-tracking branch whose fork point sits closest to HEAD.

    `exclude` drops one refname from consideration (HEAD's own remote-tracking branch). Any ref that already
    contains HEAD — a branch stacked on this one, or this commit pushed under another name — is skipped too:
    its merge-base is HEAD itself, so it would win at distance 0 and audit nothing. Returns None when no
    remote ref is related to HEAD.

    Known limit: a branch forked partway up this one still looks like the closest parent and truncates the
    range. Only naming the target branch explicitly would fix that; git history cannot tell them apart.
    """
    head = git(["rev-parse", "HEAD"], cwd)
    refs = [r for r in git(["for-each-ref", "--format=%(refname)", "refs/remotes"], cwd).split("\n") if r]
    best: str | None = None
    best_dist = float("inf")
    for ref in refs:
        if ref == exclude:
            continue
        try:
            merge_base = git(["merge-base", "HEAD", ref], cwd)
        except subprocess.CalledProcessError:
            continue  # ref unrelated to HEAD
        if merge_base == head:
            continue  # ref already contains HEAD
        dist = int(git(["rev-list", "--count", f"{merge_base}..HEAD"], cwd))
        if dist < best_dist:
            best_dist = dist
            best = merge_base
    return best


def _upstream_ref(cwd: str) -> str | None:
    try:
        return git(["rev-parse", "--symbolic-full-name", "@{u}"], cwd)
    except subprocess.CalledProcessError:
        return None


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
    upstream = _upstream_ref(cwd)
    if upstream and not manual:
        try:
            return git(["merge-base", "HEAD", upstream], cwd)
        except subprocess.CalledProcessError:
            pass  # upstream shares no history with HEAD
    base = _closest_remote_base(cwd, exclude=upstream)
    return base or git(["merge-base", "HEAD", "origin/main"], cwd)


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

    added = list(added_lines(diff))
    entries = added_comments(added)
    added_py: dict[str, set[int]] = {}
    for path, line, _ in added:
        if path.endswith(".py"):
            added_py.setdefault(path, set()).add(line)
    for path, py_lines in added_py.items():
        source = _show_blob(cwd, head, path)
        if source is not None:
            entries.extend(python_docstrings(source, path, py_lines))

    entries.sort(key=lambda e: (e["file"], e["start"]))
    return {"base": base, "head": head, "gitDir": git_dir, "comments": entries}


def _show_blob(cwd: str, head: str, path: str) -> str | None:
    try:
        return git(["show", f"{head}:{path}"], cwd, strip=False)
    except subprocess.CalledProcessError:
        return None  # deleted at HEAD, binary, ...


def _context_block(lines: list[str], entry: dict[str, Any], *, before: int, after: int) -> str:
    start, end = entry["start"], entry["end"]
    lo = max(1, start - before)
    hi = min(len(lines), end + after)
    out = [f"{entry['file']}:{start}-{end}  [{entry['kind']}]"]
    for ln in range(lo, hi + 1):
        flag = ">" if start <= ln <= end else " "
        out.append(f"  {flag}{ln:>5}  {lines[ln - 1]}")
    return "\n".join(out)


def collect_for_review(cwd: str) -> dict[str, Any]:
    """Manual-mode collect_added_comments plus a verbatim, line-numbered `block` on each comment.

    A superset of the bare detection: every entry gains a `block` pulled straight from the HEAD blob. A
    docstring's block is quoted with the def/class owner line above it and a little body below; an inline
    comment's with the code below it — each shown against the code it is actually judged against.
    """
    data = collect_added_comments(cwd, manual=True)
    blobs: dict[str, list[str] | None] = {}
    for entry in data["comments"]:
        path = entry["file"]
        if path not in blobs:
            source = _show_blob(cwd, data["head"], path)
            blobs[path] = None if source is None else source.split("\n")
        lines = blobs[path]
        if lines is None:
            entry["block"] = f"{path}:{entry['start']}-{entry['end']}  [blob unreadable]"
            continue
        before, after = (3, 2) if entry["kind"] == "docstring" else (0, 5)
        entry["block"] = _context_block(lines, entry, before=before, after=after)
    return data


def stamp_approval(cwd: str) -> tuple[str, Path]:
    """Record HEAD in the approval marker.

    Resolves the git dir the same way the gate does, so a worktree stamps where its own gate will look.
    """
    head = git(["rev-parse", "HEAD"], cwd)
    git_dir = git(["rev-parse", "--absolute-git-dir"], cwd)
    marker = Path(git_dir) / MARKER_NAME
    _ = marker.write_text(head + "\n", encoding="utf-8")
    return head, marker


def _mode(cwd: str) -> str:
    """Read `mode` from the project's comment-audit.toml; anything absent or unusable is `off`.

    The project root is CLAUDE_PROJECT_DIR, which the hook wiring provides; the payload's cwd is the
    fallback for a direct invocation.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    try:
        with (Path(root) / CONFIG_RELPATH).open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return MODE_OFF
    mode = config.get("mode")
    mode = mode.strip().lower() if isinstance(mode, str) else None
    return mode if mode in _MODES else MODE_OFF


def _render_entry(c: dict[str, Any]) -> str:
    loc = f"  {c['file']}:{c['start']}"
    if c["start"] != c["end"]:
        loc += f"-{c['end']}"
    if c["kind"] == "docstring":
        loc += "  [docstring]"
    body = "\n".join(f"      {r}" for r in c["raws"])
    return f"{loc}\n{body}"


def _report(info: dict[str, Any], *, blocking: bool) -> str:
    comments = info["comments"]
    listing = "\n".join(_render_entry(c) for c in comments)
    if blocking:
        header = f"comment-gate: this push adds {len(comments)} source comment(s) that have not been audited."
        bypass = (
            "\n(If a human wants to skip the audit, they run git push themselves — there is no agent-settable bypass.)"
        )
    else:
        header = (
            f"comment-gate: this push added {len(comments)} un-audited source comment(s). It was let through,\n"
            "but audit them now — before this branch is reviewed, not after."
        )
        bypass = (
            "\nThe push has already landed, so auditing costs one more commit and nothing else. Every comment\n"
            "below ships to whoever reads this code next; shipping one that restates the code is a decision,\n"
            "and it should be a deliberate one rather than the result of skipping this."
        )
    span = f"Added comments in {info['base'][:8]}..{info['head'][:8]}:"
    return f"{header}\n\n{_GUIDANCE}{bypass}\n\n{span}\n{listing}\n"


def _emit_warning(message: str) -> None:
    """Report without blocking.

    systemMessage surfaces the warning to the human; additionalContext is what Claude actually reads, and
    is the only channel that works here — PreToolUse plain stdout goes to the debug log, not the model.
    No permissionDecision is set, so the normal permission flow runs and the push proceeds.
    """
    payload = {
        "systemMessage": message,
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message},
    }
    _ = sys.stdout.write(json.dumps(payload))


def _marker_matches_head(info: dict[str, Any]) -> bool:
    """Report whether the approval marker names the current HEAD.

    A match consumes the marker: approval is single-use, so a later push that adds new comments has to be
    audited again rather than riding on the previous stamp.
    """
    marker = Path(str(info["gitDir"])) / MARKER_NAME
    try:
        if marker.read_text(encoding="utf-8").strip() == info["head"]:
            marker.unlink()  # consume — a later push with new comments must be re-audited
            return True
    except OSError:
        pass  # no valid marker
    return False


def _emit(message: str, *, mode: str) -> None:
    """Report an unaudited push, or a gate that could not do its job, as the mode dictates.

    `block` refuses the push — including when the gate broke, since letting an undetermined push through
    would defeat it. `warn` reports and lets the push proceed. `off` stays quiet even about its own
    failures — a gate that was told not to react does not get to speak up because it broke.
    """
    if mode == MODE_BLOCK:
        _ = sys.stderr.write(message)
        sys.exit(2)
    if mode == MODE_WARN:
        _emit_warning(message)


def _pushes_current_branch(cwd: str, args: list[str]) -> bool:
    """Report whether this is `git push [<flags>] [<remote> [<current branch>|HEAD]]`.

    The collector and the approval marker only know HEAD, so only a push of the current branch can be
    audited. An allowlist rather than a refspec parser: anything else — another ref, a deletion, a push
    option — is reported as unaudited and left to _emit, and a human pushes it directly.
    """
    rest = [a for a in args if not _is_allowed_push_flag(a)]
    if any(a.startswith("-") for a in rest):
        return False
    match rest:
        case [] | [_]:
            return True  # push.default picks the ref
        case [_, branch]:
            return branch in {"HEAD", git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)}
        case _:
            return False


def _is_allowed_push_flag(arg: str) -> bool:
    return arg in _PUSH_ALLOWED_FLAGS or arg.startswith("--force-with-lease=")


def _unaudited_push_reason(cwd: str, push: PushInvocation) -> str | None:
    if push.repo_override:
        return (
            "comment-gate: --git-dir/--work-tree pushes are not audited. Drop the option, or have a human run "
            "git push directly.\n"
        )
    if not _pushes_current_branch(cwd, push.args):
        return (
            "comment-gate: only `git push [-u|-f|--force-with-lease|--no-verify] [<remote> [<current branch>]]` "
            "is audited. Push the current branch that way, or have a human run git push directly.\n"
        )
    return None


def _push_cwd(data: dict[str, Any], push: PushInvocation) -> str:
    cwd = Path(data.get("cwd") or ".")
    for chdir in push.chdirs:
        cwd /= chdir  # an absolute -C replaces cwd, a relative one descends, as in git
    return str(cwd)


def _gate() -> None:
    # The hook fires on every Bash call, so the mode is resolved only once the command is known to be a
    # push; until then there is no project to read it from.
    mode: str | None = None
    try:
        data = json.loads(sys.stdin.read() or "{}")
        push = parse_push(data.get("tool_input", {}).get("command") or "")
        if push is None:
            return  # not a push — nothing to gate

        cwd = _push_cwd(data, push)
        mode = _mode(cwd)
        if mode == MODE_OFF:
            return

        reason = _unaudited_push_reason(cwd, push)
        if reason:
            _emit(reason, mode=mode)
            return

        info = collect_added_comments(cwd)
        if info["comments"] and not _marker_matches_head(info):
            _emit(_report(info, blocking=mode == MODE_BLOCK), mode=mode)
    except Exception as exc:  # noqa: BLE001 — a broken gate must still fail closed in `block`
        # A failure before the push's own project was known still has to honour a `block` project, rather
        # than inherit the silent default.
        _emit(
            f"comment-gate: could not audit this push ({exc!r}). Have a human run git push directly if the "
            "comments have been reviewed.\n",
            mode=mode or _mode("."),
        )


def _usage() -> NoReturn:
    _ = sys.stderr.write(f"Usage: {sys.argv[0]} gate | {sys.argv[0]} {{list|stamp}} <repo-root>\n")
    sys.exit(1)


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        _usage()
    verb = argv[0]
    if verb == "gate":
        _gate()
        return
    if len(argv) != VERB_AND_ROOT_ARGC:
        _usage()
    cwd = argv[1]
    if verb == "list":
        _ = sys.stdout.write(json.dumps(collect_for_review(cwd), indent=2) + "\n")
        return
    if verb == "stamp":
        head, marker = stamp_approval(cwd)
        _ = sys.stdout.write(f"comment-audit: stamped {head} at {marker}\n")
        return
    _usage()


if __name__ == "__main__":
    main()
