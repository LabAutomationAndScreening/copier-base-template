---
name: fix-mutants
description: Runs mutmut mutation testing and closes the gaps it finds by strengthening tests until surviving mutants are killed. Use when the user wants to run mutation testing, kill surviving mutants, improve test effectiveness, or says "fix mutants" / "run mutmut".
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion
---

# Fix Mutants

## Purpose

A surviving mutant is a change to the source that the test suite failed to
detect — proof of a missing or weak assertion, not a code bug. This skill runs
mutmut, enumerates surviving mutants, and drives a per-mutant loop: understand
the mutation, strengthen the test that should have caught it, and verify the
mutant is now killed.

The deterministic mechanics (running mutmut, parsing its per-file `.meta`
state, computing status, re-verifying a single mutant) live in the Python
scripts beside this file. The model's job is the judgement: deciding which
gap is worth closing and writing the right assertion.

## Prerequisites

- There exists a `pyproject.toml` file with a `[tool.mutmut]` table.
- `uv` is available; mutmut is installed in the project environment.
- Scripts can be run from the repo root or from inside the subfolder containing `pyproject.toml` —
  they locate the `[tool.mutmut]` root by searching upward then up to two
  levels downward.

> **Invoke every script by its path directly** (e.g.
> `{ABSOLUTE_PATH_TO_REPOSITORY_ROOT}/.claude/skills/fix-mutants/list-survived.py`). They are executable,
> stdlib-only, and have shebangs. Do **not** prefix with `uv run python`.
> The scripts call `uv run mutmut` internally.

## Conventions

**Show source paths to the user as absolute paths** so they are Ctrl+clickable
in VS Code. The scripts emit project-relative `source_file` values (relative to
the subfolder containing `pyproject.toml`); prepend the path to that subfolder before displaying. Capture the path to the
subfolder once:

```bash
.claude/skills/fix-mutants/run-mutmut.py   # its first run establishes mutants/ under the root
```

## Workflow

### Step 0: Decide how to start

```bash
.claude/skills/fix-mutants/check-results.py
```

This runs `mutmut results` and reports whether a prior run exists.

**REQUIRED — always ask via `AskUserQuestion` before proceeding:**

- If `has_results` is **false** (no prior run): offer one option only:
  - **Run mutmut (clean)** — wipe `mutants/` and run from scratch

- If `has_results` is **true** (prior run exists): offer three options:
  - **Run mutmut (clean)** — wipe `mutants/` and run from scratch; most
    trustworthy baseline but takes the longest
  - **Run mutmut (cached)** — reuse existing mutants, only re-test what changed;
    faster, good for iterating after test edits
  - **Use existing results** — skip straight to Step 2 using the results already
    on disk; fastest, use when mutmut was just run externally

Then proceed to Step 1 (if running mutmut) or Step 2 (if using existing results).

### Step 1: Run the mutation suite

```bash
# clean:
.claude/skills/fix-mutants/run-mutmut.py --clean

# cached:
.claude/skills/fix-mutants/run-mutmut.py
```

Output is a JSON status breakdown:

```json
{ "generated": "done in 2230ms (23 files mutated, 65 ignored, 0 unmodified)",
  "counts": {"killed": 180, "survived": 22, "no tests": 3},
  "total": 205, "actionable": 25 }
```

This step can take minutes (full suite per mutant). If `actionable` is 0,
report a clean bill of health and stop.

### Step 2: Enumerate the gaps

```bash
.claude/skills/fix-mutants/list-survived.py
```

Returns actionable mutants (`survived` + `no tests`) grouped by source file.
Present a summary to the user — count per file — and confirm scope.

**REQUIRED — do not skip even if there is only one file or all counts are small:**
Use `AskUserQuestion` to ask which file(s) to work through (or "all"). Only
proceed to Step 3 after the user answers.

> **Triage note.** `no tests` means the mutated line is executed by *no* test
> at all — the gap is a missing test, not a weak assertion. `survived` means a
> test runs the line but does not assert on its effect. Both are in scope;
> mention which kind each mutant is when presenting it.

### Step 3: Per-line-group loop

The **unit of work is a line group**: all surviving mutants that share the same
`source_file` and `line`. A single strengthened assertion usually kills every
mutant on that line at once, so treat them together.

The loop is driven by calling `group-by-line.py` repeatedly. Each call returns
the **next unresolved group** based on live meta state — calling it again
without resolving the current group just returns the same group. Accumulate
`--skip-line N` flags for any lines the user has chosen to skip.

```bash
# First call (and after each kill):
.claude/skills/fix-mutants/group-by-line.py <source_file> [--skip-line N ...]
```

When `done: true` is returned, all groups for this file are resolved.

For each group returned:

1. **Read** the `source_file` around `line` and the tests in `tests_for_line`.
   Form a view: *what observable behavior changes under these mutations, and why
   does no current assertion notice?*

2. **Decide and present** to the user before changing anything:
   ```
   Line <line> of <subfolder_root>/<source_file> — <N> mutant(s)
   (<remaining_lines> lines remaining incl. this one)

   Mutant 1 (status: survived | no tests):
   <diff>

   Mutant 2 ...: <diff>

   Currently exercised by: <tests_for_line, or "no tests">

   My plan: <which test to add/strengthen and the assertion that distinguishes
   original from all mutants on this line>
   ```
   Ask via AskUserQuestion: **Strengthen test** / **Skip (equivalent or not worth it)**
   / **Discuss first**.

   - Some mutants are *equivalent* — the mutated code is behaviorally identical
     to the original (e.g. a mutation inside dead code, or a default that is
     always overridden). These cannot be killed and should be skipped, not
     chased. Call them out explicitly; offer the user a `# pragma: no mutate`
     on that line or a `do_not_mutate` entry as the durable suppression.

3. **Strengthen the test** following the project's TDD discipline. The mutants
   *are* the failing cases: write/adjust the assertion so the test passes on the
   original and would fail on every mutant in the group. Follow `AGENTS.md`
   testing rules (tight mock assertions, no magic values, presence-before-absence,
   etc.). Run the single affected test first (`uv run pytest <path>::<test>
   --no-cov`) and confirm it is green on real code.

4. **Verify every mutant in the group is dead:**
   ```bash
   .claude/skills/fix-mutants/verify-mutant.py <mutant_name>
   ```
   Run for each mutant in the group. Exit 0 = killed. If any survive, the
   assertion doesn't distinguish all variants — return to step 3. Do not call
   `group-by-line.py` again until all are killed (or the user agrees to skip).

5. **Advance:** call `group-by-line.py` again (killed mutants are gone from meta;
   add `--skip-line <line>` if the user chose to skip this group). Process the
   next group returned, or stop if `done: true`.

### Step 4: Re-baseline and report

After a batch, optionally re-run `run-mutmut.py` (no `--clean` is fine) to
confirm the actionable count dropped and no new mutants appeared from edited
tests. Report:

- Mutants killed (with the test added/changed for each)
- Mutants skipped as equivalent (with the suppression applied, if any)
- Remaining actionable count

## Guidelines

**DO**
- Treat each surviving mutant as a precise, executable description of a missing
  assertion.
- Verify every fix with `verify-mutant.py` before claiming the gap is closed.
- Identify equivalent mutants honestly rather than contorting a test to kill an
  un-killable mutation.
- Make one logical test change per mutant so a failed verify points at one edit.

**DON'T**
- Modify source code to kill a mutant — the fix is almost always in the tests.
  (If the mutant reveals a real bug, surface it to the user separately; that is
  out of scope for a test-strengthening pass.)
- Weaken or delete other tests to make the suite pass.
- Suppress a mutant (`pragma`/`do_not_mutate`) without the user agreeing it is
  equivalent or out of scope.
- Batch many test edits then one verify — verify per mutant.

## Checklist

- [ ] `check-results.py` → ask user: clean / cached / use existing
- [ ] `run-mutmut.py [--clean]` → baseline status breakdown (skip if using existing)
- [ ] `list-survived.py` → actionable mutants by file; confirm scope with user (AskUserQuestion, required)
- [ ] Per file: `group-by-line.py <source_file>` → iterate by_line in order → read source + tests → present plan → approve (AskUserQuestion, required)
- [ ] Strengthen the test; confirm it passes on real code
- [ ] `verify-mutant.py <name>` for every mutant in group → all killed (exit 0) before advancing
- [ ] Re-baseline; report killed / skipped-equivalent / remaining
