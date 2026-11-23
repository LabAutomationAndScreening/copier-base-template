#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Run one input under one or more arms, one run at a time, in one run folder.

Usage:
  run.py --mode project --folder <run folder> --arms-dir <dir> --arms base d --input <prompt.txt> --id <name>
         --results <dir> [--runs 1 2]
  run.py --mode pasted --folder <run folder> --arms base d --input '<dir>/{arm}-<name>.txt' --id <name>
         --results <dir> [--runs 1 2]

An arm is one version of the guidance: `base` is the file as it stands, and every other arm differs from it by
one line (arms.py checks that). In project mode each arm is a directory under --arms-dir whose files are copied
into the run folder before its runs, so the CLI loads them as project instructions; the same prompt serves every
arm. In pasted mode the guidance is already inside each arm's prompt, so --input names one file per arm through
the `{arm}` placeholder, and the run folder stays empty.

Every arm of an input runs in the same folder, so the path the model sees never differs between arms. The folder
must be empty when the runs begin, and only the files this invocation placed in it are removed. To run
inputs side by side, start one of these per input, each with a run folder of its own.

The baseline goes first, and a candidate arm is refused while its input has no baseline result. Without the
baseline there is no telling which catches the existing guidance already makes, or which ones a new wording loses.

Each result is written to <results>/<arm>-<id>-run<N>.json, with the CLI's stderr beside it as .err. An existing
result is never overwritten unless --overwrite is given, since a rerun costs tokens and replaces evidence.

Prints one JSON line per run. Stops at the first run that fails or takes more than one turn.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from harness import MODES
from harness import PROJECT
from harness import HarnessError
from harness import add_cli_arguments
from harness import check_run_folder
from harness import cli_settings
from harness import place_arm
from harness import read_result
from harness import remove_placed_files
from harness import require_empty_run_folder
from harness import run_cli

_ARM_NAME_RE = re.compile(r"[a-z0-9]+")
_ARM_PLACEHOLDER = "{arm}"


class _PlanError(HarnessError):
    pass


def _baseline_first(*, arms: list[str], baseline: str) -> list[str]:
    return sorted(arms, key=lambda arm: arm != baseline)


def _check_plan(args: argparse.Namespace) -> None:
    unusable = [arm for arm in args.arms if _ARM_NAME_RE.fullmatch(arm) is None]
    if unusable:
        raise _PlanError(
            f"Arm names are lower-case letters and digits only, so result names can be read back: {unusable}"
        )
    if args.mode == PROJECT:
        if args.arms_dir is None:
            raise _PlanError("--arms-dir is required in project mode")
        missing = [arm for arm in args.arms if not (args.arms_dir / arm).is_dir()]
        if missing:
            raise _PlanError(f"No directory under {args.arms_dir} for: {missing}")
        return
    if _ARM_PLACEHOLDER not in args.input:
        raise _PlanError(f"In pasted mode --input must contain {_ARM_PLACEHOLDER}, since each arm has its own prompt")


def _prompt_for(*, args: argparse.Namespace, arm: str) -> str:
    return Path(args.input.replace(_ARM_PLACEHOLDER, arm)).read_text(encoding="utf-8")


def _has_baseline_result(*, results: Path, baseline: str, input_id: str) -> bool:
    return any(results.glob(f"{baseline}-{input_id}-run*.json"))


def _run_all(args: argparse.Namespace) -> int:
    folder: Path = args.folder.resolve()
    results: Path = args.results.resolve()
    check_run_folder(folder)
    require_empty_run_folder(folder)
    placed: set[Path] = set()
    try:
        for arm in _baseline_first(arms=args.arms, baseline=args.baseline):
            if arm != args.baseline:
                if not _has_baseline_result(results=results, baseline=args.baseline, input_id=args.id):
                    raise _PlanError(
                        f"No {args.baseline} result for {args.id} yet. Run the baseline first, and look at it:"
                        " if it does not show the problem, a candidate arm has nothing to fix."
                    )
            prompt = _prompt_for(args=args, arm=arm)
            for run_number in args.runs:
                name = f"{arm}-{args.id}-run{run_number}"
                result_path = results / f"{name}.json"
                if result_path.exists() and not args.overwrite:
                    raise _PlanError(f"{result_path} exists. Pass other --runs numbers, or --overwrite to replace it.")
                remove_placed_files(folder=folder, placed=placed)
                placed = set()
                if args.mode == PROJECT:
                    placed = place_arm(arm_tree=args.arms_dir / arm, folder=folder)
                exit_code = run_cli(
                    settings=cli_settings(args), mode=args.mode, folder=folder, prompt=prompt, result_path=result_path
                )
                if exit_code != 0:
                    _ = sys.stderr.write(
                        f"{name}: the CLI exited with {exit_code}. See {result_path.with_suffix('.err')}\n"
                    )
                    return 1
                result = read_result(result_path)
                summary = {
                    "run": name,
                    "turns": result.turns,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                    "is_error": result.is_error,
                }
                _ = sys.stdout.write(f"{json.dumps(summary)}\n")
                _ = sys.stdout.flush()
                if result.is_error:
                    _ = sys.stderr.write(f"{name}: the run reported an error. See {result_path}\n")
                    return 1
                if result.turns != 1:
                    _ = sys.stderr.write(f"{name}: took {result.turns} turns. With tools off a run is one turn.\n")
                    return 1
    finally:
        remove_placed_files(folder=folder, placed=placed)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--mode", choices=MODES, required=True)
    _ = parser.add_argument("--folder", type=Path, required=True, help="run folder outside every repository")
    _ = parser.add_argument("--arms-dir", type=Path, default=None, help="directory holding one directory per arm")
    _ = parser.add_argument("--arms", nargs="+", required=True)
    _ = parser.add_argument("--input", required=True, help=f"prompt file; in pasted mode with {_ARM_PLACEHOLDER} in it")
    _ = parser.add_argument("--id", required=True, help="name of this input, used in result names")
    _ = parser.add_argument("--results", type=Path, required=True)
    _ = parser.add_argument("--runs", type=int, nargs="+", default=[1, 2], help="run numbers to make (default: 1 2)")
    _ = parser.add_argument("--baseline", default="base", help="name of the arm holding the guidance as it stands")
    _ = parser.add_argument("--overwrite", action="store_true")
    add_cli_arguments(parser)
    args = parser.parse_args()

    try:
        _check_plan(args)
        return _run_all(args)
    except HarnessError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    except OSError as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1
    except subprocess.TimeoutExpired as error:
        _ = sys.stderr.write(f"{error}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
