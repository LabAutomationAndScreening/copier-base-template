#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Build one reviewing prompt per arm: the arm's guidance, the code to judge, the task, and the reply format.

Usage:
  assemble.py --arms-dir <dir> --task-file <task.txt> --code <shown path>=<local file> [--code ...]
              --id <batch name> --out-dir <dir> [--guidance AGENTS.md [--guidance ...]] [--arms base d]

Writes <out-dir>/<arm>-<id>.txt for each arm, which is the `{arm}` pattern run.py reads in pasted mode. The
prompts of two arms are the same bytes except for the guidance, so a difference in verdicts can only come from
the guidance.

--guidance names a guidance file inside each arm, by its path relative to the arm. Repeat it when the guidance
is split across files, such as AGENTS.md and .claude/rules/python.md: each file is pasted under its own path,
in the order given, as a real reader is given them apart. One file is pasted bare. A rules file loses its
`paths:` frontmatter on the way in, as it does in project mode (see harness.as_delivered).

--code takes the path the reviewer should be shown, then the local file to read. They differ on purpose: an
excerpt file built for the batch is shown under a path a real project would have.

--task-file holds the one or two sentences saying what to judge and what to leave alone, for example: "Task:
decide whether any of these tests' names violate that guidance. Use the test bodies only as evidence about the
names; do not review the bodies themselves." A narrow task is a best case for a rule. It shows what the wording
decides when a reader is looking, not whether a reader would look.

The reply format asks for the guidance sentence each finding relies on. That is what tells a catch made by the
new line from one the existing guidance already makes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from harness import as_delivered

_HEAD = (
    "You are reviewing code against a project's written guidance. Everything you need is in this message.\n"
    "\n"
    "The project's guidance is between the <guidance> tags. It is the only guidance that applies.\n"
    "\n"
    "<guidance>\n"
)
_AFTER_GUIDANCE = (
    "</guidance>\n"
    "\n"
    "The files below are excerpts from larger files: imports, helpers and neighbouring code may be left out.\n"
    "\n"
)
_REPLY_FORMAT = (
    "Reply with only this JSON, with no prose around it:\n"
    '{"findings": [{"item": "<enough of the item to find it again: a test\'s first eight words, or a function\'s'
    ' name>", "phrase": "<the offending words>", "guidance": "<the guidance sentence it violates, quoted>", "why":'
    ' "<one sentence>"}], "notes": "<anything you could not judge, or an empty string>"}\n'
    "Return an empty findings array if nothing violates the guidance.\n"
)
_CODE_SEPARATOR = "="
_DEFAULT_GUIDANCE = "AGENTS.md"


def _with_final_newline(text: str) -> str:
    if text.endswith("\n"):
        return text
    return f"{text}\n"


def _code_blocks(code: list[str]) -> str:
    blocks: list[str] = []
    for entry in code:
        shown_path, separator, local_file = entry.partition(_CODE_SEPARATOR)
        if not separator:
            raise ValueError(f"--code takes <shown path>{_CODE_SEPARATOR}<local file>, got: {entry}")
        content = _with_final_newline(Path(local_file).read_text(encoding="utf-8"))
        blocks.append(f'<file path="{shown_path}">\n{content}</file>\n\n')
    return "".join(blocks)


def _guidance_block(*, arm_tree: Path, guidance: list[str]) -> str:
    texts: dict[str, str] = {}
    for relative in guidance:
        text = (arm_tree / relative).read_text(encoding="utf-8")
        texts[relative] = _with_final_newline(as_delivered(relative=Path(relative), text=text))
    if len(texts) == 1:
        return next(iter(texts.values()))
    return "\n".join(f'<file path="{relative}">\n{text}</file>\n' for relative, text in texts.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--arms-dir", type=Path, required=True)
    _ = parser.add_argument("--arms", nargs="+", default=None, help="default: every arm under --arms-dir")
    _ = parser.add_argument(
        "--guidance",
        action="append",
        default=None,
        help=f"guidance file inside each arm; repeat for several, in reading order (default: {_DEFAULT_GUIDANCE})",
    )
    _ = parser.add_argument("--task-file", type=Path, required=True)
    _ = parser.add_argument("--code", action="append", required=True, metavar="SHOWN=LOCAL")
    _ = parser.add_argument("--id", required=True, help="name of this batch, used in file names")
    _ = parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    arms: list[str] = args.arms
    guidance_files: list[str] = [_DEFAULT_GUIDANCE]
    if args.guidance is not None:
        guidance_files = args.guidance
    if arms is None:
        arms = sorted(path.name for path in args.arms_dir.iterdir() if path.is_dir())
    try:
        after_guidance = (
            _AFTER_GUIDANCE
            + _code_blocks(args.code)
            + _with_final_newline(args.task_file.read_text(encoding="utf-8").strip())
            + "\n"
            + _REPLY_FORMAT
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for arm in arms:
            guidance = _guidance_block(arm_tree=args.arms_dir / arm, guidance=guidance_files)
            prompt_path: Path = args.out_dir / f"{arm}-{args.id}.txt"
            _ = prompt_path.write_text(_HEAD + guidance + after_guidance, encoding="utf-8")
            _ = sys.stdout.write(f"{prompt_path}  {prompt_path.stat().st_size} bytes\n")
    except OSError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    except ValueError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
