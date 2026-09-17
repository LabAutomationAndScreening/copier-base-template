#!/usr/bin/env python3
"""PreToolUse hook: reacts to the agent's `git push` adding un-audited source comments.

Why: when addressing PR review comments the agent tends to leave behind source comments that either
restate what the code does (WHAT-comments) or are really the reply to the reviewer. Those should be
removed; only comments explaining a non-obvious WHY earn their place. This gate is the tripwire — it does
NOT judge the comments itself. It detects that the outgoing push adds source comments and, unless they
have been audited, says so and points at the `comment-audit` skill.

Division of labour:
  - gate  (this file): deterministic detection + attestation check. Cheap, no LLM.
  - skill (comment-audit): the actual review — classify each comment, review every one with the human
    (keep/drop/edit), apply decisions, then stamp the attestation marker (comment-audit.py stamp) and push.

Modes:
  - warn  (the default): report the un-audited comments and let the push through. The agent sees the
    listing as hook context and can choose to run the audit; nothing is ever blocked.
  - block: refuse the push until the skill has stamped approval. The enforcing mode.
  - off:   do nothing.

The mode comes from `mode` in <project>/.config/comment-audit.toml, which the template renders from the
`comment_audit_gate_mode` copier answer. COMMENT_GATE_MODE overrides the file for a one-off or a test.
Anything missing, unreadable, or unrecognised falls back to `warn` — a gate that cannot read its own
config should nag, not block, and certainly not vanish.

`warn` is the default on purpose: the detector's precision on a given repo is unknown until it has run
against real branches, and a false positive in `warn` is noise where in `block` it is a work stoppage.
Move a project to `block` once warn-mode reports have proven trustworthy.

Scope: Claude Code PreToolUse hook → only intercepts the AGENT's `git push`. A human running `git push`
directly is never affected — that, or the skill's attestation, is the only way past `block`. There is
deliberately no agent-settable override: an env flag the agent could add itself would be no gate.

Attestation: the skill writes <git-dir>/.comment-audit-ok containing the HEAD sha it reviewed. A marker
matching the current HEAD silences the gate (and is then consumed) in every mode, so `warn` and `block`
agree on what counts as audited. This stops the accidental/forgetful bypass; it is not proof against an
adversarial agent (a file is a file).

Reads the Claude Code hook payload as JSON on stdin. Exit 0 allows the push; exit 2 blocks it. In `warn`
mode the report is emitted as hook JSON on stdout — PreToolUse plain stdout only reaches the debug log.
"""

import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import MARKER_NAME
from utils import collect_added_comments
from utils import is_git_push

MODE_ENV = "COMMENT_GATE_MODE"
MODE_OFF = "off"
MODE_WARN = "warn"
MODE_BLOCK = "block"
CONFIG_RELPATH = Path(".config") / "comment-audit.toml"

_GUIDANCE = (
    "Run the comment-audit skill — invoke /comment-audit. It reviews every comment with you\n"
    "(why-not-what; drops what-restatements, reply text, and historical narration), applies your\n"
    "keep/drop/edit decisions, stamps approval, and pushes."
)


def _normalise(raw: str) -> str | None:
    """Map a configured value onto a mode, or None when it names none of them."""
    cleaned = raw.strip().lower()
    if cleaned == MODE_OFF:
        return MODE_OFF
    if cleaned == MODE_WARN:
        return MODE_WARN
    if cleaned == MODE_BLOCK:
        return MODE_BLOCK
    return None


def _configured_mode(cwd: str) -> str | None:
    """Read `mode` from the project's comment-audit.toml, or None if it is absent or unusable.

    The project root is CLAUDE_PROJECT_DIR, which the hook wiring provides; the payload's cwd is the
    fallback for a direct invocation.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        root = cwd
    try:
        with (Path(root) / CONFIG_RELPATH).open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None  # no config, or not parseable
    mode = config.get("mode")
    if not isinstance(mode, str):
        return None
    return _normalise(mode)


def _mode(cwd: str) -> str:
    override = _normalise(os.environ.get(MODE_ENV, ""))
    if override:
        return override
    configured = _configured_mode(cwd)
    if configured:
        return configured
    return MODE_WARN


def _render_entry(c: dict[str, Any]) -> str:
    loc = f"  {c['file']}:{c['start']}"
    if c["start"] != c["end"]:
        loc += f"-{c['end']}"
    if c.get("kind") == "docstring":
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
            f"comment-gate (warn mode): this push adds {len(comments)} source comment(s) that have not been\n"
            "audited. The push is NOT blocked."
        )
        bypass = (
            "\n(Warn mode is advisory. Push again after auditing, or proceed as-is if the comments earn their place.)"
        )
    span = f"Added comments in {str(info['base'])[:8]}..{str(info['head'])[:8]}:"
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
    """Report whether the approval marker names the current HEAD, consuming it when it does."""
    marker = Path(str(info["gitDir"])) / MARKER_NAME
    try:
        if marker.read_text(encoding="utf-8").strip() == info["head"]:
            marker.unlink()  # consume — a later push with new comments must be re-audited
            return True
    except OSError:
        pass  # no valid marker
    return False


def _fail(message: str, *, mode: str) -> None:
    """Handle a gate that could not do its job.

    Fails closed in `block`, where letting an undetermined push through would defeat the gate. In `warn`
    nothing is enforced anyway, so the failure is reported and the push proceeds.
    """
    if mode == MODE_BLOCK:
        _ = sys.stderr.write(message)
        sys.exit(2)
    _emit_warning(message)


def main() -> None:
    # Until the payload says where the project is, an unexpected failure is handled as `warn`. The hook
    # fires on every Bash call, so the mode is resolved only once the command is known to be a push.
    mode = MODE_WARN
    try:
        data = json.loads(sys.stdin.read() or "{}")
        command = (data.get("tool_input", {}).get("command") or "").strip()
        if not is_git_push(command):
            return  # not a push — nothing to gate

        cwd = data.get("cwd") or data.get("tool_input", {}).get("cwd") or "."
        mode = _mode(cwd)
        if mode == MODE_OFF:
            return

        try:
            info = collect_added_comments(cwd)
        except Exception:  # noqa: BLE001 — can't reason about the repo; don't leak comments
            _fail(
                "comment-gate: could not determine the push range. Resolve it, or have a human run git push directly.\n",
                mode=mode,
            )
            return

        if not info["comments"]:
            return  # nothing added — push freely
        if _marker_matches_head(info):
            return  # audited at this HEAD — allow

        if mode == MODE_BLOCK:
            _ = sys.stderr.write(_report(info, blocking=True))
            sys.exit(2)
        _emit_warning(_report(info, blocking=False))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — unexpected failure; fail closed where the gate enforces
        _fail(
            "comment-gate: internal error. Have a human run git push directly if the comments have been reviewed.\n",
            mode=mode,
        )


if __name__ == "__main__":
    main()
