#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""Check that every arm differs from the baseline by one line, and print what that line is.

Usage: arms.py --arms-dir <dir> [--baseline base]

Each directory under --arms-dir is an arm: a copy of the guidance files as a run folder should hold them (an
AGENTS.md, a `.claude/rules/` tree, or both). The baseline arm holds the guidance as it stands in the file the
rule will live in, taken from the last commit and not from a working tree that may already carry the proposed
change.

An arm passes when it has the same files as the baseline and, across all of them, at most one line removed and at
most one line added: a bullet added, a bullet reworded, or a sentence taken out to see what it was doing. Two
arms that differ in anything more cannot be compared, because a difference in results could come from either
change.

Prints each arm's changed lines and a digest of its files, so a report can say exactly what was tested. Exits
non-zero if any arm fails.

Lines are compared as runs are given them. A rules file whose frontmatter has `paths:` reaches a run without that
frontmatter (see harness.as_delivered), and the script lists such files with a line for the report saying their
delivery was not tested.
"""

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from harness import as_delivered
from harness import files_under
from harness import rules_files_with_paths


def _digest(tree: Path) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files_under(tree)):
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update((tree / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def _changed_lines(*, baseline_tree: Path, arm_tree: Path) -> tuple[list[str], list[str]]:
    removed: list[str] = []
    added: list[str] = []
    for relative in sorted(files_under(baseline_tree)):
        before = as_delivered(
            relative=relative, text=(baseline_tree / relative).read_text(encoding="utf-8")
        ).splitlines()
        after = as_delivered(relative=relative, text=(arm_tree / relative).read_text(encoding="utf-8")).splitlines()
        matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
        for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
            if tag == "equal":
                continue
            removed.extend(f"{relative}: {line}" for line in before[before_start:before_end])
            added.extend(f"{relative}: {line}" for line in after[after_start:after_end])
    return removed, added


def _report(*, arm: str, baseline_tree: Path, arm_tree: Path) -> bool:
    _ = sys.stdout.write(f"\n{arm}  (digest {_digest(arm_tree)})\n")
    if files_under(arm_tree) != files_under(baseline_tree):
        only_here = sorted(str(path) for path in files_under(arm_tree) - files_under(baseline_tree))
        only_there = sorted(str(path) for path in files_under(baseline_tree) - files_under(arm_tree))
        _ = sys.stdout.write(
            f"  FAIL: not the same files as the baseline. Extra: {only_here}. Missing: {only_there}.\n"
        )
        return False
    removed, added = _changed_lines(baseline_tree=baseline_tree, arm_tree=arm_tree)
    for line in removed:
        _ = sys.stdout.write(f"  - {line}\n")
    for line in added:
        _ = sys.stdout.write(f"  + {line}\n")
    if not removed and not added:
        _ = sys.stdout.write("  FAIL: identical to the baseline, so there is nothing to compare.\n")
        return False
    if len(removed) > 1:
        _ = sys.stdout.write(f"  FAIL: {len(removed)} lines removed. An arm may differ by one line.\n")
        return False
    if len(added) > 1:
        _ = sys.stdout.write(f"  FAIL: {len(added)} lines added. An arm may differ by one line.\n")
        return False
    _ = sys.stdout.write("  ok\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _ = parser.add_argument("--arms-dir", type=Path, required=True)
    _ = parser.add_argument("--baseline", default="base")
    args = parser.parse_args()

    baseline_tree: Path = args.arms_dir / args.baseline
    if not baseline_tree.is_dir():
        _ = sys.stderr.write(f"No baseline arm at {baseline_tree}\n")
        return 1
    if not files_under(baseline_tree):
        _ = sys.stderr.write(f"The baseline arm at {baseline_tree} holds no files\n")
        return 1
    _ = sys.stdout.write(f"{args.baseline}  (digest {_digest(baseline_tree)})  the guidance as it stands\n")
    scoped = rules_files_with_paths(baseline_tree)
    if scoped:
        listed = ", ".join(str(relative) for relative in scoped)
        _ = sys.stdout.write(
            f"Runs get {listed} without the paths: frontmatter, as if each had loaded. Delivery through paths:"
            " (whether the rule is in context when a matching file is touched) was not tested.\n"
        )
    arms = sorted(path.name for path in args.arms_dir.iterdir() if path.is_dir() and path.name != args.baseline)
    if not arms:
        _ = sys.stderr.write(f"No arm besides the baseline under {args.arms_dir}\n")
        return 1
    passed = [_report(arm=arm, baseline_tree=baseline_tree, arm_tree=args.arms_dir / arm) for arm in arms]
    if all(passed):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
