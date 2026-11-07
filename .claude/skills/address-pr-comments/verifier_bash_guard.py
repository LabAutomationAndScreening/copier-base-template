#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse hook for the ai-review-verifier agent: block Bash commands that change a repo, write to GitHub or write files.

The verifier reads a thread anyone with access to the PR can reply in, and the project's permissions allow commands such
as `git push` without asking, so text in the thread could talk it into one. Its instructions say to treat that text as
data; this hook enforces the worst of it. It is a deny-list on purpose: a review agent needs commands nobody listed in
advance, so everything not named here runs. Blocked, in any piece of a command (split on `;`, `&&`, `||`, `|`, `&`,
newlines, `$(` and backticks, double-quoted ones included, and through the wrappers `env`, `xargs`, `timeout`, `sudo`, `nice`, `nohup`, `command`,
`exec` and `time`, a shell's `-c` (`-lc` too) and `eval`):

- git commands that change a repo or its remote: push, commit, merge, rebase, reset, checkout, switch, restore,
  cherry-pick, revert, tag, stash, clean, rm, mv, add, apply, am, worktree, update-ref, notes, gc; `branch` deleting or
  renaming; `remote` other than listing; `config` setting or unsetting.
- gh commands other than its reads: list, view, status, diff, checks and watch in any group, `gh search`, `gh help`,
  and `gh api` with GET and no fields or input. gh's write commands are open-ended, so this one list is of reads.
- rm and rmdir, and redirecting output into a file (`>/dev/null` and `2>&1` are fine).
- a shell running a script file or stdin rather than `-c`, `source` and `.`, and `env -S`: the guard can't see what
  they run.
- a heredoc with an unquoted delimiter, or one that is never closed. A quoted heredoc's body (`<<'EOF'`) is data, such
  as a verdict's text, and isn't checked.

Its verdict goes up through the post command in its prompt (post_verdict.py), which none of this blocks. Exit code 2
blocks the command and shows the agent the reason on stderr, so it can find a read-only way.
"""

import json
import re
import shlex
import sys

_BLOCKED_GIT = frozenset(
    {
        "push",
        "commit",
        "merge",
        "rebase",
        "reset",
        "checkout",
        "switch",
        "restore",
        "cherry-pick",
        "revert",
        "tag",
        "stash",
        "clean",
        "rm",
        "mv",
        "add",
        "apply",
        "am",
        "worktree",
        "update-ref",
        "notes",
        "gc",
    }
)
_GIT_BRANCH_CHANGES = frozenset({"-d", "-D", "-m", "-M", "--delete", "--move"})
_GIT_REMOTE_READS = frozenset({"show", "get-url"})
_GIT_CONFIG_CHANGES = frozenset(
    {"--unset", "--unset-all", "--add", "--replace-all", "--rename-section", "--remove-section", "--edit", "-e"}
)
_GIT_CONFIG_SUBCOMMAND_CHANGES = frozenset({"set", "unset", "rename-section", "remove-section", "edit"})
# git's own options before the subcommand that take the next word as their value
_GIT_OPTIONS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})
# gh's verbs that only read, in any group; every other verb writes or might, so it is blocked
_GH_READ_VERBS = frozenset({"list", "view", "status", "diff", "checks", "watch"})
_GH_READ_GROUPS = frozenset({"search", "help"})
_GH_REPO_OPTIONS = frozenset({"-R", "--repo"})
_GH_API_FIELD_FLAGS = ("-f", "-F", "--field", "--raw-field", "--input")
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", "|&"})
_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
# wrappers that run the rest of their words as a command, each with its options that take the next word as their value
_WRAPPER_OPTIONS_WITH_VALUE = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "command": frozenset(),
    "nohup": frozenset(),
    "exec": frozenset({"-a"}),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "xargs": frozenset(
        {
            "-n",
            "--max-args",
            "-I",
            "-L",
            "--max-lines",
            "-P",
            "--max-procs",
            "-d",
            "--delimiter",
            "-s",
            "--max-chars",
            "-E",
            "-a",
            "--arg-file",
        }
    ),
    "sudo": frozenset(
        {
            "-u",
            "--user",
            "-g",
            "--group",
            "-C",
            "--close-from",
            "-D",
            "--chdir",
            "-h",
            "--host",
            "-p",
            "--prompt",
            "-r",
            "--role",
            "-t",
            "--type",
            "-U",
            "--other-user",
        }
    ),
}
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_SHELL_OPTIONS_WITH_VALUE = frozenset({"-o", "+o", "-O", "+O"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# group 1 is `-` for `<<-`, which strips leading tabs; group 2 or 3 a quoted delimiter, group 4 an unquoted one
_HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|([^\s;&|<>()'\"]+))")


class BlockedError(Exception):
    pass


def _quote_after(*, char: str, quote: str | None) -> str | None:
    """Return the quote bash is inside (`'`, `"` or None) after reading `char` while inside `quote`."""
    if quote == "'":
        if char == "'":
            return None
        return quote
    if char == '"':
        if quote == '"':
            return None
        return '"'
    if char == "'":
        if quote is None:
            return "'"
    return quote


def _skip_heredoc_bodies(*, command: str, start: int, pending: list[tuple[str, bool]]) -> int:
    """Return the index just past the bodies of the heredocs `pending` names, which begin at `start`, in order."""
    index = start
    for delimiter, strip_tabs in pending:
        while True:
            if index >= len(command):
                raise BlockedError(f"it has a heredoc whose closing line {delimiter!r} never comes")
            end = command.find("\n", index)
            if end == -1:
                end = len(command)
            line = command[index:end]
            index = end + 1
            if strip_tabs:
                line = line.lstrip("\t")
            if line == delimiter:
                break
    return index


def _without_heredoc_bodies(command: str) -> str:
    """Drop each heredoc's body (data fed to a command's stdin, such as a verdict's text) and its `<<'EOF'` marker.

    Only a `<<` that bash reads as one counts: not inside quotes, after a backslash, or in a `<<<` here-string. Bash
    expands `$(…)` in the body of a heredoc whose delimiter is unquoted, so that body isn't plain data and such a heredoc
    is blocked, as is one whose closing line never comes.
    """
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            kept.append(command[index : index + 2])
            index += 2
            continue
        if quote is None and command.startswith("<<<", index):
            kept.append("<<<")
            index += 3
            continue
        if quote is None and command.startswith("<<", index):
            index = _heredoc_marker(command=command, index=index, pending=pending)
            continue
        if char == "\n" and quote is None and pending:
            kept.append(char)
            index = _skip_heredoc_bodies(command=command, start=index + 1, pending=pending)
            pending = []
            continue
        quote = _quote_after(char=char, quote=quote)
        kept.append(char)
        index += 1
    if pending:
        raise BlockedError(f"it has a heredoc whose closing line {pending[0][0]!r} never comes")
    return "".join(kept)


def _heredoc_marker(*, command: str, index: int, pending: list[tuple[str, bool]]) -> int:
    """Record the heredoc whose `<<` starts at `index` in `pending`, and return the index just past its marker."""
    marker = _HEREDOC.match(command, index)
    if marker is None:
        raise BlockedError("it has a `<<` with no heredoc delimiter after it")
    if marker.group(4) is not None:
        raise BlockedError(
            f"its heredoc delimiter {marker.group(4)!r} is unquoted, so bash runs any `$(…)` in the body;"
            f" quote it (<<'{marker.group(4)}')"
        )
    delimiter = marker.group(2) if marker.group(2) is not None else marker.group(3)
    pending.append((delimiter, marker.group(1) == "-"))
    return marker.end()


def _substitution_end(*, text: str, start: int) -> int:
    """Return the index of the `)` that closes the `$(` whose contents begin at `start`."""
    depth = 1
    quote: str | None = None
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote is None:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        quote = _quote_after(char=char, quote=quote)
        index += 1
    raise BlockedError("it has a `$(` that is never closed")


def _substitutions(text: str) -> list[str]:
    """Return the commands in each `$(…)` and backtick pair bash runs in `text`, double-quoted ones included.

    shlex keeps a double-quoted word whole, so `echo "$(git push)"` would otherwise reach the checks as `echo` and one
    argument. Single-quoted text is literal, as in bash.
    """
    found: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote != "'" and text.startswith("$(", index):
            end = _substitution_end(text=text, start=index + 2)
            found.append(text[index + 2 : end])
            index = end + 1
            continue
        if quote != "'" and char == "`":
            end = text.find("`", index + 1)
            if end == -1:
                raise BlockedError("it has a backtick that is never closed")
            found.append(text[index + 1 : end])
            index = end + 1
            continue
        quote = _quote_after(char=char, quote=quote)
        index += 1
    return found


def _segments(text: str) -> list[list[str]]:
    """Split a command, its heredoc bodies removed, into the argv of each simple command in it, checking redirections."""
    # newlines and backticks start a new command too, and shlex reads a newline as plain whitespace
    text = text.replace("\n", " ; ").replace("`", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    words = list(lexer)
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if word in _SEPARATORS:
            segments.append([])
            continue
        if word in _REDIRECTS:
            target = words[index] if index < len(words) else ""
            index += 1
            if segments[-1] and segments[-1][-1].isdigit():
                # the file descriptor written before a redirection (`2>`) is part of it, not an argument
                _ = segments[-1].pop()
            if target == "/dev/null":
                continue
            if word == ">&":
                if target.isdigit():
                    continue
            raise BlockedError(f"it redirects output into the file {target!r}")
        if word == "$":
            # `$(` reaches here as `$` then `(`: the `(` starts the substituted command
            continue
        segments[-1].append(word)
    return [segment for segment in segments if segment]


def _past_options(args: list[str], *, wrapper: str) -> list[str]:
    """Return a wrapper's arguments past its own options, skipping the value of each option that takes one."""
    with_value = _WRAPPER_OPTIONS_WITH_VALUE[wrapper]
    index = 0
    while index < len(args):
        word = args[index]
        if word == "--":
            return args[index + 1 :]
        if not word.startswith("-"):
            break
        if wrapper == "env":
            if word.startswith(("-S", "--split-string")):
                raise BlockedError("`env -S` splits a string into a command the guard can't check")
        if word in with_value:
            index += 2
            continue
        index += 1
    return args[index:]


def _unwrapped(argv: list[str]) -> list[str]:
    """Return the command a wrapper such as `env NAME=value`, `xargs -n 1`, `timeout 5` or `sudo -u x` runs."""
    while argv:
        word = argv[0]
        if _ENV_ASSIGNMENT.match(word) is not None:
            argv = argv[1:]
            continue
        wrapper = word.rsplit("/", 1)[-1]
        if wrapper not in _WRAPPER_OPTIONS_WITH_VALUE:
            return argv
        argv = _past_options(argv[1:], wrapper=wrapper)
        if wrapper == "timeout":
            # the duration comes before the command
            argv = argv[1:]
    return argv


def _shell_script(args: list[str]) -> str | None:
    """Return the script a shell's `-c` runs (`-c`, `-lc`, `-ec`, …), or None when it runs a script file or stdin."""
    runs_string = False
    index = 0
    while index < len(args):
        word = args[index]
        if word in _SHELL_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if word.startswith("--"):
            index += 1
            continue
        if len(word) > 1 and word[0] in "-+":
            if "c" in word[1:]:
                runs_string = True
            index += 1
            continue
        if runs_string:
            return word
        return None
    return None


def _git_subcommand(args: list[str]) -> list[str]:
    """Return git's subcommand and its arguments, past git's own options such as `-C <path>`."""
    index = 0
    while index < len(args):
        word = args[index]
        if word in _GIT_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if not word.startswith("-"):
            break
        index += 1
    return args[index:]


def _positional(args: list[str]) -> list[str]:
    return [word for word in args if not word.startswith("-")]


def _check_git_config(rest: list[str]) -> None:
    for word in rest:
        if word in _GIT_CONFIG_CHANGES:
            raise BlockedError(f"`git config {word}` changes the repo's config")
    positional = _positional(rest)
    if not positional:
        return
    if positional[0] in _GIT_CONFIG_SUBCOMMAND_CHANGES:
        raise BlockedError(f"`git config {positional[0]}` changes the repo's config")
    if positional[0] == "get":
        return
    if len(positional) > 1:
        raise BlockedError("`git config <key> <value>` sets a config value")


def _check_git(args: list[str]) -> None:
    subcommand = _git_subcommand(args)
    if not subcommand:
        return
    verb, rest = subcommand[0], subcommand[1:]
    if verb in _BLOCKED_GIT:
        raise BlockedError(f"`git {verb}` changes the repo or its remote")
    if verb == "branch":
        for word in rest:
            if word in _GIT_BRANCH_CHANGES:
                raise BlockedError(f"`git branch {word}` deletes or renames a branch")
        return
    if verb == "remote":
        positional = _positional(rest)
        if positional:
            if positional[0] not in _GIT_REMOTE_READS:
                raise BlockedError(f"`git remote {positional[0]}` changes the repo's remotes")
        return
    if verb == "config":
        _check_git_config(rest)


def _gh_api_method(*, word: str, following: str) -> str | None:
    """Return the HTTP method a `gh api` option sets (`-X POST`, `-XPOST`, `--method=POST`), or None if it sets none."""
    if word == "-X":
        return following
    if word == "--method":
        return following
    if word.startswith("--method="):
        return word.removeprefix("--method=")
    if word.startswith("-X"):
        return word.removeprefix("-X")
    return None


def _gh_api_field_flag(word: str) -> str | None:
    """Return the `gh api` option sending fields or input that a word is (`-f k=v`, `-fk=v`, `--field=k=v`), if any."""
    for flag in _GH_API_FIELD_FLAGS:
        if word == flag:
            return flag
        if word.startswith(f"{flag}="):
            return flag
    if word.startswith("--"):
        return None
    # short options take their value attached too
    for flag in ("-f", "-F"):
        if word.startswith(flag):
            return flag
    return None


def _check_gh_api(rest: list[str]) -> None:
    for index, word in enumerate(rest):
        following = rest[index + 1] if index + 1 < len(rest) else ""
        method = _gh_api_method(word=word, following=following)
        if method is not None:
            if method.upper() != "GET":
                raise BlockedError(f"`gh api --method {method}` writes to GitHub")
            continue
        flag = _gh_api_field_flag(word)
        if flag is not None:
            raise BlockedError(f"`gh api {flag}` sends fields or input, which makes it a write")


def _gh_words(args: list[str]) -> list[str]:
    """Return gh's words that aren't options, past `-R`/`--repo` and its value, so the group and verb come first."""
    words: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        if word in _GH_REPO_OPTIONS:
            index += 2
            continue
        if not word.startswith("-"):
            words.append(word)
        index += 1
    return words


def _check_gh(args: list[str]) -> None:
    words = _gh_words(args)
    if words[:1] == ["api"]:
        _check_gh_api(args[args.index("api") + 1 :])
        return
    if not words[1:]:
        # bare `gh`, `gh --version`, or a group alone, which prints its help
        return
    group, verb = words[0], words[1]
    if group in _GH_READ_GROUPS:
        return
    if verb not in _GH_READ_VERBS:
        raise BlockedError(
            f"`gh {group} {verb}` isn't one of gh's read-only commands ({', '.join(sorted(_GH_READ_VERBS))})"
        )


def _check(argv: list[str]) -> None:
    argv = _unwrapped(argv)
    if not argv:
        return
    program = argv[0].rsplit("/", 1)[-1]
    args = argv[1:]
    if program in _SHELLS:
        script = _shell_script(args)
        if script is None:
            raise BlockedError(f"`{program}` without -c runs a script file or stdin the guard can't check")
        _check_command(script)
        return
    if program in ("source", "."):
        raise BlockedError(f"`{program}` runs a script file the guard can't check")
    if program == "eval":
        _check_command(" ".join(args))
        return
    if program in ("rm", "rmdir"):
        raise BlockedError(f"`{program}` deletes files")
    if program == "git":
        _check_git(args)
        return
    if program == "gh":
        _check_gh(args)


def _check_command(command: str) -> None:
    text = _without_heredoc_bodies(command)
    for substituted in _substitutions(text):
        _check_command(substituted)
    for argv in _segments(text):
        _check(argv)


def main() -> int:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    try:
        _check_command(command)
    except BlockedError as e:
        _ = sys.stderr.write(
            f"Blocked: {e}. The verifier reads git objects and posts only through the post command in its prompt;"
            " find a read-only way to check this.\n"
        )
        return 2
    except ValueError as e:
        _ = sys.stderr.write(f"Blocked: the command couldn't be parsed to check it ({e}); write it more simply.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
