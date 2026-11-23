# Authoring tests

An authoring test asks an agent to write something and looks at whether the defect is in it. It answers the
question a rule usually exists for: does this wording change what gets written?

## Why the obvious test shows nothing

The obvious test hands an agent some finished code with the names blanked and asks it to fill them in under the
guidance. In the experiment this skill came from, that produced no defect at all under any arm, so there was
nothing for a rule to prevent and nothing learned.

The defect had come from somewhere the test left out. Authors wrote "returns false without raising" because
they had just fixed a function that raised, and the title recorded what they knew. An agent shown only the
finished test knows none of that.

So before writing a scenario, work out where the defect comes from: what the author knew, or saw, or was asked,
that the finished code does not show. Then put that in.

## Scenarios

Each scenario is one request, as a user would type it, with the files the author needs.

- **Give the author what a real author knew.** For a defect that records a fixed bug, the request states the
  bug and the fix as facts: what went wrong, under what input, and what the code does now.
- **Never mention the guidance.** In real use nobody points at the rule. It has to act from the project
  instructions alone, and a request that names it turns the test into a reviewing test.
- **Keep the defect's own words out of the request.** If the defect is a title ending "instead of throwing",
  do not write "instead of" yourself. State the old failure and let the author choose how to put it.
- **Use real code**, copied by line range and unedited: the unit under test, and the file the new code goes
  into with the target and its near-twins left out. A near-twin left in is copied, and then the test measures
  copying.
- **One artifact per run.** Several in one run share whatever style the author settles on first, so they are
  one sample, not several.
- **Give every request the same shape**, so that scenarios differ in their code and not in how they were asked.
- **Say there are no tools**, attach the files, and ask for the new code alone in one code block.

A request for a title-defect scenario, in full:

```text
I fixed a bug in `reports/save.py`. When the target folder did not exist, `save_report` raised
`FileNotFoundError` from inside the error handler, and that exception replaced the original failure in the
log. The fix is the `try`/`except OSError`: the function now returns `False` when it cannot write the file.

Write the regression test for this fix, to go in `tests/unit/test_save.py`.

There are no tools in this session, so the files you need are below. Reply with the new test alone, in one code
block and nothing else.
```

Build each prompt with a small script that copies the code ranges and checks each still holds what it should,
as for real reviewing cases.

## The baseline gate

Run the baseline arm on the scenarios first, twice each, and read what it wrote.

- **If the defect appears** in a fair share of the results, the scenarios work. Go on to the candidate.
- **If it does not appear**, do not run a candidate. Either the scenarios leave out what produces the defect,
  or it does not arise this way. Change the scenarios, or report that authoring could not be tested and why.

A candidate arm run against a baseline that shows no defect costs the same and can only say "no difference".

## Testing a removal

An arm that removes a sentence asks the opposite question: does the defect appear once the sentence is gone?
The gate turns around with it.

- **The baseline must not write the defect.** If it does, the sentence is not preventing it in that scenario,
  and removing it can show nothing there. Report that as a finding about the sentence, and stop on that scenario.
- **The removal arm is the one expected to write it.** A defect under the removal arm that the baseline never
  wrote is work the sentence was doing.

What a removal test turns on is whether anything else in the author's context already carries the convention.
Build each scenario twice:

- **Bare**: the request and the unit under test, with no code nearby that follows the convention.
- **With neighbours**: the same request, plus the file the new code goes into, copied unedited, where the
  existing code follows the convention. This is what most real authors see.

Run both arms on both versions, baseline first, even when the baseline's answer seems obvious. `run.py`
refuses the removal arm on an input with no baseline result, because a removal arm alone shows what it writes
and not what changed.

Read the two versions together. "Lost" means the removal arm wrote the defect where the baseline did not:

| Bare | With neighbours | What the sentence does |
|---|---|---|
| Lost | Lost | Carries the convention on its own |
| Lost | Kept | Covers the author who has nothing to copy, such as the first file of its kind |
| Kept | Kept | Nothing these scenarios can show |
| Kept | Lost | Unexpected: check that the neighbouring code follows the convention, then run again |

Whether the bare case is worth a sentence is the user's call, not the test's. Put beside it what else would
catch the defect: a linter or type checker that fails the code costs a round trip, and a defect nothing checks
ships. With tools off, the run cannot show whether the author would have fixed it after such a failure.

Controls still apply when the sentence restricts something: a removal arm can show what the sentence was
wrongly making authors drop.

## Controls

A rule can do harm by making authors drop something true. Add scenarios where the thing the rule restricts is
legitimately needed: if the rule discourages claims that something did not happen, add fixes whose whole point
is that something no longer happens, where the right result both says so and checks it.

Run both arms on the controls. What matters is whether the candidate keeps what the baseline kept.

## Marks

Decide the marks before the runs and put them in the key with your predictions. For a rule about titles:

| Mark | Meaning |
|---|---|
| Defect | The thing the rule is meant to stop, as the user ruled it |
| Propped | The defect, plus something added only to justify it, such as a check that could never fail on its own |
| Clean | Neither |

And for a control:

| Mark | Meaning |
|---|---|
| Kept and checked | The legitimate thing is stated, and backed |
| Stated, not backed | It is stated with nothing behind it |
| Dropped | It is neither stated nor backed |

Read every result yourself. A word search finds candidates and misses the same idea in other words. If a result
fits none of the marks, add a mark and say so, instead of forcing it into the nearest one.

Also note, without a mark, what else changed between the arms: weaker or stronger checks, extra artifacts
nobody asked for, a different structure. Two runs per scenario cannot prove a side effect, but they are where
one is first seen.

## Running

```bash
.claude/skills/test-guidance-wording/run.py --mode project --folder <run folder> --arms-dir <arms> --arms base --runs 1 --input <experiment>/authoring/prompts/<scenario>.txt --id <scenario> --results <experiment>/authoring/results
.claude/skills/test-guidance-wording/tally.py --results <experiment>/authoring/results --replies --id <scenario>
```

That single run goes alone. Then the baseline's remaining runs on every scenario, then, if the gate is
passed, the candidate (`--arms a`).

- **In series**, one scenario per call, reading the replies before the next.
- **In parallel**, start one call per scenario together, each with a run folder of its own. Every arm of a
  scenario runs in that scenario's folder, so the path the model sees is the same for both arms.

Project mode costs more per run than pasted mode, because each run carries the CLI's own system prompt and the
whole guidance file before the scenario begins. Estimate with the overhead the canary reported.

## What an authoring test cannot show

Say these in the report where they apply.

- **A rule's effect on a defect the baseline never wrote.** No number of runs fixes that; only a better
  scenario does.
- **Copying.** If no neighbouring code in the prompt carries the defect, the test says nothing about an author
  who imitates what is already in the file.
- **Long sessions.** A real author has an hour of context behind it. A run has one message.
- **Tools.** With tools off the author writes from pasted files and cannot explore, and a rules file scoped by
  `paths:` never loads.
- **Other readers.** One model at one effort level is one reader.
