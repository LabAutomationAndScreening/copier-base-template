#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Ask one run what is in its context, to prove a run folder is isolated before any arm is trusted.

Usage:
  canary.py --mode project --folder <empty folder outside every repository> [--with-rules-file] [--save <result.json>]
  canary.py --mode pasted  --folder <empty folder outside every repository> [--save <result.json>]

In project mode the folder is given a small AGENTS.md carrying a random codeword, which is removed afterwards. The
run is asked whether it has project instructions, to quote the codeword and the sentence that introduces them, and
what else it was given. A passing project-mode canary reports exactly one instruction file, at the run folder's
path, quotes this run's codeword, and reports no style instruction, no memory notes, no list of skills and no
tools. A passing pasted-mode canary reports no project instructions at all.

With --with-rules-file, the folder also gets .claude/rules/canary.md with a second codeword, as run.py places a
rules file: without `paths:` frontmatter. Run it whenever arms hold rules files. A pass then reports two
instruction files and quotes both codewords.

The script prints the reply, the token counts, and whether the codeword came back. Reading the rest of the reply is
the caller's job: only a person or an agent can tell that "one file, at this path" is what the answer says.

The input token count of a project-mode canary is the harness's fixed overhead, give or take the few hundred
tokens of the questions themselves.
"""

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from harness import MODES
from harness import PROJECT
from harness import RULES_DIR
from harness import HarnessError
from harness import RunResult
from harness import add_cli_arguments
from harness import check_run_folder
from harness import cli_settings
from harness import read_result
from harness import run_cli

_QUESTIONS = """Do not use any tools. Answer only from what is already in your context, in plain numbered sentences.

1. Besides this message, do you have project instructions in your context, such as the contents of an AGENTS.md or CLAUDE.md file or a rules file? Answer yes or no.
2. If yes: how many separate instruction files appear in your context? For each one, give the path shown for it, quote its first heading, and quote any codeword it gives. Also quote, word for word, the sentence or two that introduce those instructions to you.
3. Were you given any instruction about response style, such as writing tersely? If so, quote one line of it and say where it comes from.
4. Which model are you, as far as your context says?
5. For each of these, say whether it is present in your context, without quoting it: a working directory, a git status, a user's email address, memory notes from earlier sessions, a list of skills, a list of tools you can call.
"""


def _canary_guidance(codeword: str) -> str:
    return f"# Canary project notes\n\nThe project codeword is {codeword}.\n"


def _canary_rule(codeword: str) -> str:
    return f"# Canary rules\n\nThe rules codeword is {codeword}.\n"


def _remove_placed(*, folder: Path, placed: list[Path]) -> None:
    for relative in placed:
        (folder / relative).unlink(missing_ok=True)
    for relative in placed:
        for parent in relative.parents:
            directory = folder / parent
            if parent != Path() and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()


class _CanaryError(HarnessError):
    pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--mode", choices=MODES, required=True)
    _ = parser.add_argument("--folder", type=Path, required=True, help="empty run folder outside every repository")
    _ = parser.add_argument(
        "--with-rules-file", action="store_true", help="project mode: also place a rules file with its own codeword"
    )
    _ = parser.add_argument("--save", type=Path, default=None, help="keep the raw result here")
    add_cli_arguments(parser)
    return parser.parse_args()


def _check_empty_run_folder(folder: Path) -> None:
    check_run_folder(folder)
    if any(folder.iterdir()):
        raise _CanaryError(f"{folder} is not empty. The canary needs a folder with nothing in it.")


def _codewords(*, with_rules_file: bool) -> dict[Path, str]:
    codewords = {Path("AGENTS.md"): f"PLUM-{secrets.token_hex(4)}"}
    if with_rules_file:
        codewords[RULES_DIR / "canary.md"] = f"PEAR-{secrets.token_hex(4)}"
    return codewords


def _place_codewords(*, folder: Path, codewords: dict[Path, str]) -> list[Path]:
    placed: list[Path] = []
    for relative, codeword in codewords.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        if relative.is_relative_to(RULES_DIR):
            content = _canary_rule(codeword)
        else:
            content = _canary_guidance(codeword)
        _ = (folder / relative).write_text(content, encoding="utf-8")
        placed.append(relative)
    return placed


def _result_path(*, save: Path | None, folder: Path) -> Path:
    if save is None:
        return folder.parent / f"{folder.name}-canary.json"
    saved = save.resolve()
    if saved.is_relative_to(folder):
        raise _CanaryError(
            f"--save {saved} is the run folder or inside it, where the result would count as a stray file or be"
            " removed with the codewords. Save it beside the run folder instead."
        )
    return saved


def _ask(*, args: argparse.Namespace, folder: Path, codewords: dict[Path, str], result_path: Path) -> RunResult:
    placed: list[Path] = []
    if args.mode == PROJECT:
        placed = _place_codewords(folder=folder, codewords=codewords)
    try:
        exit_code = run_cli(
            settings=cli_settings(args), mode=args.mode, folder=folder, prompt=_QUESTIONS, result_path=result_path
        )
    except OSError as error:
        raise _CanaryError(f"The CLI could not be run to the end: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise _CanaryError(f"The CLI could not be run to the end: {error}") from error
    finally:
        _remove_placed(folder=folder, placed=placed)
    if exit_code != 0:
        raise _CanaryError(f"The CLI exited with {exit_code}. See {result_path.with_suffix('.err')}")
    return read_result(result_path)


def _report(*, result: RunResult, result_path: Path, mode: str, codewords: dict[Path, str]) -> int:
    _ = sys.stdout.write(f"{result.reply}\n\n")
    _ = sys.stdout.write(f"turns: {result.turns}\n")
    _ = sys.stdout.write(f"input tokens: {result.input_tokens}\n")
    _ = sys.stdout.write(f"output tokens: {result.output_tokens}\n")
    _ = sys.stdout.write(f"raw result: {result_path}\n")
    if mode != PROJECT:
        _ = sys.stdout.write(
            "pasted mode: a pass is a reply reporting no project instructions and no style instruction\n"
        )
        return 0
    all_quoted = True
    for relative, codeword in codewords.items():
        if codeword in result.reply:
            _ = sys.stdout.write(f"codeword {codeword} ({relative}): quoted, so that file was loaded\n")
        else:
            _ = sys.stdout.write(f"codeword {codeword} ({relative}): NOT quoted, so that file did not reach the run\n")
            all_quoted = False
    if all_quoted:
        return 0
    return 1


def main() -> int:
    args = _parse_args()
    folder: Path = args.folder.resolve()
    if args.with_rules_file and args.mode != PROJECT:
        _ = sys.stderr.write("--with-rules-file needs --mode project: pasted mode places no files.\n")
        return 1
    codewords = _codewords(with_rules_file=args.with_rules_file)
    try:
        result_path = _result_path(save=args.save, folder=folder)
        _check_empty_run_folder(folder)
        result = _ask(args=args, folder=folder, codewords=codewords, result_path=result_path)
    except HarnessError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    return _report(result=result, result_path=result_path, mode=args.mode, codewords=codewords)


if __name__ == "__main__":
    sys.exit(main())
