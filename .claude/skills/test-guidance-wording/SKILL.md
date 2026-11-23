---
name: test-guidance-wording
description: Tests whether a rule in AGENTS.md or a .claude/rules/ file does what it is meant to, before it ships. Runs isolated headless agents under the guidance as it stands and under each candidate wording, scores them against answers the user settled first, and recommends a wording with its evidence and limits. A one-clause edit to an existing rule, such as one a PR reviewer asks for, takes a quick mode of about 30,000 tokens; a new rule takes the full process. Use it whenever how a rule is phrased is in question, not only when asked to "test" one.
when_to_use: /test-guidance-wording, "will this rule cause false positives or false negatives", "can this rule be tightened", "test this AGENTS.md change", "which wording is better", "does this bullet actually work", "is this rule doing anything", "why do agents keep doing X despite the rule", a review comment (human or AI) asking to reword, tighten or scope a rule, even by one clause and even mid-backport, a new or reworded rule headed for a shared template, or before splitting or condensing guidance when nothing must be lost.
user-invocable: true
allowed-tools: Bash(.claude/skills/test-guidance-wording/canary.py *), Bash(.claude/skills/test-guidance-wording/run.py *), Bash(.claude/skills/test-guidance-wording/arms.py *), Bash(.claude/skills/test-guidance-wording/assemble.py *), Bash(.claude/skills/test-guidance-wording/tally.py *), Bash(git show *), Bash(git log *), Bash(git grep *), Bash(git blame *), Bash(git diff *), Bash(git status *), Read, Write, Edit, AskUserQuestion
argument-hint: "<the rule or the proposed change, and what it is meant to stop>"
---

# Test the wording of agent guidance

## Purpose

A rule in `AGENTS.md` is read by two kinds of agent: the one writing code and the one reviewing it. Its
wording decides what each does, and reading the rule does not tell you what that is. A sentence that sounds
right can flag a correct case, pass the very defect it names, or switch off a catch the guidance around it was
already making.

This skill finds out by running agents that see only the guidance under test: the file as it stands, then the
same file with one line changed, on cases whose right answers were settled first. It ends with a recommendation
(which wording, or none), the evidence for it, and what the evidence does not cover.

It fits rules about what agents write or flag: names, comments, structure, what a test asserts. It does not fit
rules about tool use ("never run the linter directly"). Those need tools switched on and a sandbox, which this
harness does not have.

## Conventions

- **Runs are headless CLI calls, never Agent-tool subagents.** A subagent started from a session inherits the
  repository's guidance, working-tree edits included, so every arm would see the same text and no two wordings
  could be told apart. The scripts here run `claude -p` with tools off, from a folder outside every repository.
- **Two kinds of folder.** The experiment lives in `<repo_root>/tmp/guidance-tests/<slug>/`, which is
  gitignored. Run folders live outside every repository, for example under the session's scratchpad or the
  system temp directory; the scripts create them and refuse a folder that could leak guidance.
- **Scripts run by their bare paths from the repo root**, never through an interpreter:
  `.claude/skills/test-guidance-wording/canary.py`, `.claude/skills/test-guidance-wording/arms.py`,
  `.claude/skills/test-guidance-wording/assemble.py`, `.claude/skills/test-guidance-wording/run.py` and
  `.claude/skills/test-guidance-wording/tally.py`. Each explains itself with `--help`.
- **Spend is not a reason to stop and ask.** Work in steps of roughly 100,000 tokens or less and go from one to
  the next on your own. The figure is a guide, not a line. Say the estimate before a step and the actual after
  it, in tokens, not cost. Ask first only when a single step would cost several times that. What does need the
  user is judgment: rulings on cases, and whether to widen the question.
- **Estimating a run.** Input is the harness's fixed overhead (the canary reports it: about 1,000 tokens in
  pasted mode, about 3,500 in project mode), plus the guidance and the prompt at roughly a third of their size
  in bytes. Output is usually 1,000 to 3,000 tokens.
- **The reader.** Runs default to `opus` at `medium` effort. Pass `--model` and `--effort` when the user names
  the model that will read the guidance in practice. Do not default to the session's own model at its highest
  effort: it costs several times more per run, and the comparison needs many runs.
- **Two runs of everything.** A verdict that differs between two identical runs is noise, and one run cannot
  show that.
- **Answers come from the user's rulings, never from a wording.** A key written to match a candidate measures
  nothing, and neither does one written from your own case design: the user confirms every label, Clean ones
  included, before the first run.
- **Write a prediction before each batch, and record afterwards in the key file where it was wrong.** A wrong
  prediction is the cheapest sign that the design, not the wording, needs changing.
- **Change nothing outside `tmp/`.** This skill tests a change. Applying it, or backporting it to a template,
  needs the user's word.
- **Code from private repositories stays in `tmp/`.** Never paste a case, a file path or a repository's name
  into a PR, an issue or a public template. Report by class and count ("tested on 47 test names from private
  repositories").
- **Long results go in files.** Give the user a short summary and the path.
- **Everything the experiment writes stays in its folder**: interim write-ups, comparisons, and the context
  behind a question to the user. A question's file may also be copied to `/tmp/<short name>` so the question
  can show a short path, but the experiment folder holds the copy that lasts. `/tmp` and the session's
  transcript are gone after a rebuild, and with them the evidence for whatever the user decided.

## Step 1: Settle how to run, and what the rule is for

First ask whether the rule turns on the agent reading, searching or running something: looking for an existing
helper, running a check, opening a file before editing it. If it does, no arm can differ here, because runs
have tools off. Say so before proposing any plan, and offer the two ways on:

- **Skip the test**, and record in the experiment's README what the change was, why it went untested, and
  who decided.
- **A tool-enabled run in a scratch repository** built to hold what the rule points at. This harness does not
  do it, and it costs roughly 100,000 to 200,000 tokens.

If the change adds, removes or rewords at most one clause or sentence of an existing rule, follow "Quick mode"
below instead of the steps that follow here. A new rule, or a rule moved between files, takes the full process.

Otherwise ask with AskUserQuestion, unless the user already said, how each batch of runs should go:

- **In series**: one input at a time, reading each result before starting the next. Slower, but a batch can
  be stopped or changed the moment a result shows the design is off, so less is spent on runs that could not
  have told you anything.
- **In parallel**: every input of a batch at once, then read them all. Faster, and the whole batch is spent
  before anything can be learned from it.

Either way, the first run of a new kind of input goes alone, as the check on format and isolation (Step 4).

Then settle, from the request or by asking:

- **The harm.** What the rule should stop, in the user's words, with an example that should be caught and one
  that should not. If the user offers a wording, ask what it is for: the wording is a candidate, not the goal.
- **The file.** Where the rule will live. That file, at its last commit, is the baseline. A rule headed for a
  shared template is tested against the template's file, not a downstream copy that may have drifted.
- **The readers.** Authors, reviewers or both, and which model reads it if the user knows.

Start `<repo_root>/tmp/guidance-tests/<slug>/README.md` now and keep it current: the rulings so far, what has
run and what it showed, tokens spent, and what is still undecided. Update it after every batch, before the next
one starts, and after every ruling, before acting on it; a README that says no run was made while results sit
beside it is worse than none. It is the experiment's record, and what lets another session, or this one after
its context is summarized, carry on without redoing anything. It is not a task list: track your own steps the
way the project's rules say to. It has these sections:

```markdown
# <the change, in a line>

## Rulings          the harm, the file and its base commit, the readers, each case ruling with its reason
## Before any run   what Step 2 found; filled before any arm is built
## Runs             per batch: arms, input, runs, tokens, what it showed, predictions that were wrong
## Undecided        what still waits on the user
```

```text
<repo_root>/tmp/guidance-tests/<slug>/
  README.md            the record: rulings, what ran, results in brief, tokens, what is undecided
  arms/<arm>/          one directory per version of the guidance
  key/                 labels and predictions; no run ever sees these
  reviewing/           the code each batch judges, inputs/ and results/
  authoring/           requests/, prompts/ and results/
  RECOMMENDATION.md    written last (or a Verdict section in README.md; see Step 8)
```

## Step 2: Look before spending anything

These cost no model tokens and can end the experiment early.

1. **Read the guidance around the rule.** Note every existing sentence that already bears on the harm. A new
   line is judged by what it adds to them, and it may lean on one of them without saying so.
2. **Find the defect in real code.** Search this repository and any other the user points to for how often
   it occurs, in what forms, and when (`git log`, `git blame`). A defect last written months ago is legacy
   that needs no rule. One that appears under words the proposed rule never mentions shows the rule is aimed
   at the wrong thing.
3. **Collect real cases**: instances of the defect, and cases that resemble it and are fine. The second kind
   matters more, since it is what a careless wording condemns.
4. **Note what surrounds the defect where it is written**: the neighbouring code an author would have had open,
   and whether it follows the convention. Authoring scenarios that leave it out test an author no one is.

Write all four into the README's "Before any run" section, with counts ("78 of 114 bare literals") and dates
rather than impressions, and tell the user what it turned up. "No rule needed" is a result. Skipping this step
tends to cost a second round of runs: a pilot that fails because the defect is rarer, or commoner,
or written differently than assumed.

## Step 3: Build the arms

Do not build an arm while the README's "Before any run" section is empty.

An arm is one version of the guidance, as a directory holding what a run folder should hold:

```text
<repo_root>/tmp/guidance-tests/<slug>/arms/base/AGENTS.md    the file as it stands
<repo_root>/tmp/guidance-tests/<slug>/arms/a/AGENTS.md       the same file with one line changed
```

- Take `base` from the last commit, with `git show <ref>:<path>`, and not from a working tree that may already
  carry the proposed change.
- Make each candidate by copying `base` and changing one line. Name arms with lower-case letters and digits
  only (`a`, `b`, `c2`).
- An arm that removes one existing sentence is how to find out what that sentence was doing.
- Run `.claude/skills/test-guidance-wording/arms.py --arms-dir <arms>`. It fails any arm that differs from the
  baseline by more than one line, and prints the changed line and a digest of each arm for the report.

## Step 4: Prove the runs are isolated

Before the first run of a session, and again whenever the session, the CLI version or the run folder changes:

```bash
.claude/skills/test-guidance-wording/canary.py --mode pasted --folder <run folder> --save <experiment>/canary-pasted.json
.claude/skills/test-guidance-wording/canary.py --mode project --folder <run folder> --save <experiment>/canary-project.json
```

When the arms hold files under `.claude/rules/`, add `--with-rules-file` to the project-mode canary. It places
a rules file with a second codeword, the way `run.py` places one, and proves such files reach a run.

Read the reply; the script can only check the codeword.

- **Pasted mode passes** when the run reports no project instructions and no style instruction beyond its
  one-line system prompt.
- **Project mode passes** when the run reports exactly one instruction file (two with `--with-rules-file`),
  under the run folder's path, quotes every codeword, and reports no style instruction, no memory notes, no
  list of skills and no tools.

A working directory and the user's email address appear in both; that is the CLI's own context and the same
for every arm. Anything else is a leak. Find it before running an arm, because a leak is the same in every arm
and so never shows up as a difference between them.

If the CLI fails with an authentication error, the shell probably holds a placeholder `ANTHROPIC_API_KEY`. The
scripts already drop that variable for the run; pass `--keep-api-key` only when a real key is how this
environment signs in. Do not print the key or read credential files to find out.

`tally.py` repeats three checks on every batch for free: one turn per run, the same input token count for
identical runs, and a constant difference between each arm and the baseline. That difference is the changed
line. A leak of a repository's guidance would add thousands of tokens.

## Step 5: Reviewing: what does the wording decide?

Read `.claude/skills/test-guidance-wording/reviewing.md` before building the first batch. In outline:

1. **A pilot of about a dozen cases**, most of them matched pairs: two cases alike in everything except the
   one thing the rule turns on. Half or more are clean. Write the answer key and your prediction for each
   arm, then have the user confirm the whole key table, not only the cases you are unsure of.
2. **Baseline first.** `run.py` refuses a candidate arm while its input has no baseline result. Read the
   baseline's reasons: the guidance sentence each finding cites shows what the file already catches without
   any new line. When the baseline flags a case labelled Clean, re-check that label with the user before
   blaming any wording; a mislabelled case corrupts every comparison after it.
3. **Then the candidates**, on the same input.
4. **Score each case as gained, lost, both or neither** against the baseline. A lost case, one the baseline
   caught and the candidate does not, is the worst outcome a wording can have, and only the baseline shows it.
5. **Decide.** If a candidate gets a case wrong for a reason its text invites, rewrite the line and rerun that
   batch. If two candidates agree everywhere, the shorter one wins.

A pilot like this costs well under 100,000 tokens and has usually told the wordings apart by its end.

## Step 6: Widen only as far as the decision needs

Stop when another batch could not change the recommendation. Until then, in this order:

- **Real cases** from Step 2, copied by line range and unedited, with the share of violations kept near what
  real code has. Synthetic cases show what a wording decides; real ones show what it meets.
- **A breaker batch**, built to make the leading wording fail: forms its examples do not name, cases its text
  covers literally but should leave alone, whatever was cut to shorten it. Predict the failure you are fishing
  for. If it does not come, that is the strongest evidence the experiment will produce.
- **An extra arm only when a named result calls for it.** Write the condition down before the batch ("run the
  longer wording only if the short one flags a clean case of this kind"), and skip the arm when it is not met.

## Step 7: Authoring: does it change what gets written?

A rule that reviewers apply correctly may still do nothing for the agent writing the code, and the defect is
cheaper never written than caught. Read `.claude/skills/test-guidance-wording/authoring.md` first. In outline:

1. **Rebuild the conditions the defect comes from.** Each scenario is a plain request that gives the author
   what a real author knew, and never mentions the guidance. The guidance arrives as project instructions
   (`--mode project`), under the CLI's own system prompt, one artifact per run.
2. **The baseline has to produce the defect.** Run the baseline arm on the scenarios first. If the defect does
   not appear, the scenarios are wrong or the problem is not reproducible this way; either way a candidate arm
   would show nothing, so do not run one. For an arm that removes a sentence, the gate turns around: the
   baseline must not produce the defect, and each scenario runs bare and with neighbouring code (see
   `authoring.md`).
3. **Then the candidate**, on the same scenarios.
4. **Then controls**: scenarios where the thing the rule restricts is legitimately needed. They are how a rule
   that makes authors drop something true gets caught.

## Step 8: Report

Write `<repo_root>/tmp/guidance-tests/<slug>/RECOMMENDATION.md` for a reader without this session's context,
and tell the user where it is. It holds:

- **What to change**: the exact line, ready to paste, and the file and place it goes. Recommend exactly the
  text that was run. A wording polished after its last run is an untested wording.
- **What follows from it** in this repository: existing code the new rule now condemns or clears, each with the
  ruling it rests on.
- **Why**, in the user's rulings and the measured cases, not in the wording's own logic.
- **The evidence**: a table per kind of test, baseline beside candidate, by class of case.
- **Limits**: who chose and labelled the cases, how many runs, which model, what was never reproduced.
- **What stays the user's to decide.**
- **What must not be pasted elsewhere.**

Then stop. Applying the change is a separate instruction.

When this skill runs as one step of a larger task, such as checking a wording during a backport, a `## Verdict`
section at the end of the README takes the place of `RECOMMENDATION.md`: the wording chosen, the evidence in a
few lines, the limits, and who decided. Write it before acting on the decision, since the larger task moves on
at once and nothing later comes back to write it.

## Quick mode

For a change of one clause or sentence to an existing rule: the kind a PR review asks for, which the full
process is too heavy for and which otherwise ships untested. It costs about 30,000 tokens. Every convention
above still holds; what it drops is breadth.

1. **README.** Start `<repo_root>/tmp/guidance-tests/<slug>/README.md` with Rulings, Runs and Verdict sections.
   Under Rulings: the clause before and after, the harm the change is meant to fix, the file and its base
   commit.
2. **A light look.** Read the sentences around the clause and note any that already bear on the harm. Run one
   search of the repository for the defect, and write the count into the README.
3. **Six cases**: three violations and three clean cases that resemble them, at least one of the six copied
   unedited from real code. Build matched pairs where the clause turns on one thing.
4. **The user confirms all six labels** before any run, as in the full process.
5. **Two arms**, `base` and the candidate, checked with `arms.py`. Run the pasted-mode canary (Step 4), then
   reviewing only (Step 5): baseline first, two runs each, four runs in all.
6. **Read the result against one test.** The candidate passes when it loses no case the baseline caught, flags
   no Clean case the baseline passed, and its two runs agree on every labelled case. Anything else stops quick
   mode: tell the user what happened and offer the full process, starting from Step 2 with these cases kept.
7. **Verdict.** Write the README's Verdict section: the clause, the six-case table with base beside candidate,
   tokens spent, and the limits (six cases, reviewers only, no authoring runs, no breaker batch). Applying the
   change still needs the user's word.

## Guidance split into rules files

A file under `<repo_root>/.claude/rules/` with no `paths:` loads at launch like `AGENTS.md`, and is tested the
same way: put it in each arm's directory at the same relative path.

A rules file with `paths:` loads only when the agent reads, writes or edits a matching file. With tools off
that never happens, so the scripts hand each run such a file without its frontmatter, as if it had loaded. Keep
the frontmatter in the arms, as the file stands. `arms.py` names every file this applies to, with a line for the
report saying delivery was not tested; paste it. Whether the rule is in context at the moment it is needed is a
separate question, and a real one: a brand-new file may be written before its rule loads, and a reviewer shown
only a diff may never load it.

In pasted mode, pass `assemble.py` one `--guidance` per file the reader would have, in the order a run loads
them, which the project-mode canary's reply lists (`--guidance .claude/rules/testing.md --guidance AGENTS.md`);
each is pasted under its own path. In project mode, run the canary with `--with-rules-file` (Step 4).

When guidance is split or condensed, the sentences a rule leans on have to travel with it unchanged. The
guidance sentence each finding cites, in the baseline's replies, is the list of what must not be lost.
