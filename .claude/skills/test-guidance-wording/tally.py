#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Read a results directory: token counts for every run, the isolation checks, and optionally the replies.

Usage: tally.py --results <dir> [--baseline base] [--replies] [--id <input name>] [--only <run name> ...]
                [--fields <field> ...]

Results are the <arm>-<id>-run<N>.json files run.py writes. The table gives each run's turns and tokens, then a
total, which is the figure to report (input and output together, cached input included).

The checks cost nothing and are how a leak shows up:

- One turn per run. Tools are off, so more than one means the harness is not what it should be.
- The runs of one arm on one input report the same input token count. Same bytes in, same count.
- Each candidate arm's input count exceeds the baseline's by the same amount on every input. That amount is the
  changed line, and nothing else differs between two arms. A repository's guidance leaking into the runs would
  add thousands of tokens.
- Every input with a candidate result also has a baseline result.

Exits non-zero when a check fails. A constant difference of zero is reported as a failure too, since it means
an arm's change never reached the runs.

--replies prints what each run answered. A reviewing reply in the findings format is laid out one finding at a
time, with the guidance sentence it cites; any other reply is printed as it came.

Two options narrow the replies without a pipe through grep, and each implies --replies. The table and the checks
always cover every run of the input, since the checks need the baseline beside each arm.

- --only prints the replies of the named runs alone, by the name the table shows (base-pilot-run2).
- --fields picks which parts of each finding to print. The flagged item is always printed, so `--fields notes`
  shows what was flagged and the run's notes, and `--fields guidance` what was flagged and the sentence cited.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from harness import ResultFormatError
from harness import RunResult
from harness import read_result

_NAME_RE = re.compile(r"(?P<arm>[a-z0-9]+)-(?P<input_id>.+)-run(?P<number>\d+)")
_FINDING_FIELDS = ("phrase", "guidance", "why", "notes")


@dataclass(frozen=True)
class _Run:
    arm: str
    input_id: str
    number: int
    result: RunResult

    @property
    def name(self) -> str:
        return f"{self.arm}-{self.input_id}-run{self.number}"


def _load(*, results: Path, only_input: str | None) -> tuple[list[_Run], list[str]]:
    runs: list[_Run] = []
    unreadable: list[str] = []
    for path in sorted(results.glob("*.json")):
        match = _NAME_RE.fullmatch(path.stem)
        if match is None:
            continue
        if only_input is not None and match["input_id"] != only_input:
            continue
        try:
            result = read_result(path)
        except ResultFormatError as error:
            unreadable.append(str(error))
            continue
        runs.append(_Run(arm=match["arm"], input_id=match["input_id"], number=int(match["number"]), result=result))
    return runs, unreadable


def _sorted(*, runs: list[_Run], baseline: str) -> list[_Run]:
    return sorted(runs, key=lambda run: (run.input_id, run.arm != baseline, run.arm, run.number))


def _write_table(*, runs: list[_Run], baseline: str) -> None:
    width = max(len(run.name) for run in runs)
    _ = sys.stdout.write(f"{'run':<{width}}  turns   input  output   total\n")
    for run in _sorted(runs=runs, baseline=baseline):
        result = run.result
        _ = sys.stdout.write(
            f"{run.name:<{width}}  {result.turns:>5}  {result.input_tokens:>6}  {result.output_tokens:>6}"
            f"  {result.total_tokens:>6}\n"
        )
    by_arm: dict[str, int] = defaultdict(int)
    for run in runs:
        by_arm[run.arm] += run.result.total_tokens
    _ = sys.stdout.write("\n")
    for arm in sorted(by_arm, key=lambda name: (name != baseline, name)):
        _ = sys.stdout.write(f"{arm}: {by_arm[arm]} tokens\n")
    _ = sys.stdout.write(f"total: {sum(by_arm.values())} tokens over {len(runs)} run(s)\n")


def _failed_checks(*, runs: list[_Run], baseline: str) -> list[str]:
    failures = [f"{run.name} took {run.result.turns} turns" for run in runs if run.result.turns != 1]
    failures.extend(f"{run.name} reported an error" for run in runs if run.result.is_error)

    input_counts: dict[tuple[str, str], set[int]] = defaultdict(set)
    for run in runs:
        input_counts[(run.input_id, run.arm)].add(run.result.input_tokens)
    for (input_id, arm), counts in sorted(input_counts.items()):
        if len(counts) > 1:
            failures.append(
                f"{arm} on {input_id}: runs of the same input report different input counts {sorted(counts)}"
            )

    differences: dict[str, dict[str, int]] = defaultdict(dict)
    for (input_id, arm), counts in sorted(input_counts.items()):
        if arm == baseline:
            continue
        if (input_id, baseline) not in input_counts:
            failures.append(f"{input_id}: {arm} has results and {baseline} has none")
            continue
        differences[arm][input_id] = min(counts) - min(input_counts[(input_id, baseline)])
    for arm, by_input in sorted(differences.items()):
        distinct = set(by_input.values())
        if len(distinct) > 1:
            failures.append(f"{arm} differs from {baseline} by a different amount on different inputs: {by_input}")
            continue
        difference = distinct.pop()
        if difference == 0:
            failures.append(f"{arm} has the same input count as {baseline}, so its change never reached the runs")
            continue
        _ = sys.stdout.write(
            f"{arm} is {baseline} {difference:+} input tokens on every input compared ({len(by_input)})\n"
        )
    return failures


def _without_code_fence(reply: str) -> str:
    return "\n".join(line for line in reply.splitlines() if not line.startswith("```"))


def _write_findings(*, parsed: dict[object, object], fields: list[str]) -> None:
    findings = parsed["findings"]
    if not isinstance(findings, list):
        _ = sys.stdout.write(f"{parsed}\n")
        return
    if not findings:
        _ = sys.stdout.write("  no findings\n")
    for finding in findings:
        if not isinstance(finding, dict):
            _ = sys.stdout.write(f"  {finding}\n")
            continue
        _ = sys.stdout.write(f"  FLAG  {finding.get('item')}\n")
        for field in ("phrase", "guidance", "why"):
            if field in fields:
                _ = sys.stdout.write(f"        {field + ':':<9} {finding.get(field)}\n")
    if "notes" in fields:
        _ = sys.stdout.write(f"  NOTES {parsed.get('notes')}\n")


def _write_replies(*, runs: list[_Run], baseline: str, fields: list[str]) -> None:
    for run in _sorted(runs=runs, baseline=baseline):
        _ = sys.stdout.write(f"\n=== {run.name}\n")
        try:
            parsed: object = json.loads(_without_code_fence(run.result.reply))
        except json.JSONDecodeError:
            _ = sys.stdout.write(f"{run.result.reply}\n")
            continue
        if isinstance(parsed, dict) and "findings" in parsed:
            _write_findings(parsed=parsed, fields=fields)
            continue
        _ = sys.stdout.write(f"{run.result.reply}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--results", type=Path, required=True)
    _ = parser.add_argument("--baseline", default="base")
    _ = parser.add_argument("--replies", action="store_true", help="also print what each run answered")
    _ = parser.add_argument("--id", default=None, help="only this input")
    _ = parser.add_argument("--only", nargs="+", default=None, metavar="RUN", help="replies of these runs alone")
    _ = parser.add_argument(
        "--fields",
        nargs="+",
        choices=_FINDING_FIELDS,
        default=None,
        help="parts of each finding to print, all by default; the flagged item always is",
    )
    args = parser.parse_args()
    show_replies = args.replies or args.only is not None or args.fields is not None
    fields = list(_FINDING_FIELDS) if args.fields is None else args.fields

    runs, unreadable = _load(results=args.results, only_input=args.id)
    for problem in unreadable:
        _ = sys.stderr.write(f"{problem}\n")
    if not runs:
        _ = sys.stderr.write(f"No readable results named <arm>-<id>-run<N>.json in {args.results}\n")
        return 1
    replied_runs = runs
    if args.only is not None:
        replied_runs = [run for run in runs if run.name in args.only]
        missing = sorted(set(args.only) - {run.name for run in replied_runs})
        if missing:
            names = ", ".join(run.name for run in _sorted(runs=runs, baseline=args.baseline))
            _ = sys.stderr.write(f"No result for {', '.join(missing)}. Runs here: {names}\n")
            return 1
    _write_table(runs=runs, baseline=args.baseline)
    _ = sys.stdout.write("\n")
    failures = _failed_checks(runs=runs, baseline=args.baseline)
    for failure in failures:
        _ = sys.stdout.write(f"CHECK FAILED: {failure}\n")
    if not failures:
        _ = sys.stdout.write("checks passed: one turn per run, stable input counts, a constant difference per arm\n")
    if show_replies:
        _write_replies(runs=replied_runs, baseline=args.baseline, fields=fields)
    if failures:
        return 1
    if unreadable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
