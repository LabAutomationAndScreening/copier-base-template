#!/usr/bin/env python3
"""Check that every path under .claude/ written in a document under .claude/ exists.

A skill's or agent's instructions name scripts by path, and an agent types a path as it is written, so a renamed or
removed file breaks those instructions silently: the agent finds out when the command fails, and may improvise. This
runs as a pre-commit hook whenever anything under .claude/ changes, reads every tracked markdown document there, and
lists each `.claude/...` path that resolves to nothing.

A path is checked up to its first placeholder or glob (`<`, `{`, `*`, `$`), so `.claude/skills/<skill>/` checks the
skills directory. A path inside a longer one, such as `~/.claude/commands/`, is an example of a file elsewhere and is
left alone. A directory counts.
"""

import re
import subprocess
import sys
from pathlib import Path

_PATH_RE = re.compile(r"(?<![\w/~])\.claude/[\w./-]*")


def _tracked_documents() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", ".claude/*.md"],  # noqa: S607 — git is expected on PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [Path(name) for name in listed.split("\0") if name]


def _references(document: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), start=1):
        # a sentence may end right after the path
        found.extend((number, match.group().rstrip(".")) for match in _PATH_RE.finditer(line))
    return found


def main() -> int:
    missing: list[str] = []
    for document in _tracked_documents():
        for number, path in _references(document):
            if Path(path).exists():
                continue
            missing.append(f"{document}:{number}: {path} does not exist")
    for problem in missing:
        _ = sys.stderr.write(f"{problem}\n")
    if missing:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
