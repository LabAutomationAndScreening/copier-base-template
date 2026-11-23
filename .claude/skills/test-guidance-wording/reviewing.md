# Reviewing tests

A reviewing test shows a reviewer the guidance and some code and asks what violates it. It answers one
question: given that a reader is looking, what does this wording make them decide?

It is a best case. The task tells the reviewer exactly where to look, and a reviewer reading a whole diff may
not look there at all. So a reviewing test can show that a wording is wrong. It cannot show that a rule will
be applied.

## Cases

Start with cases you write yourself, because only then is there exactly one difference between two of them.

- **Build matched pairs.** For each thing the rule turns on, write two cases alike in everything else. For a
  rule about test titles that claim something did not happen: one title ending "without calling the pricing
  API" above a body that checks the API was not called, and one ending "without raising" above a body that
  checks only the return value.
- **Make half or more of the cases clean.** Include the ones that resemble the defect, which a careless
  wording would condemn, and a few plain cases with none of the rule's vocabulary in them.
- **For each kind of case, name what a wording could get wrong, and make sure a case would show it**: flagging
  a correct case, missing the defect in another phrasing, missing it when a nearby check seems to cover it,
  applying the rule outside the place it is about.
- **Keep the code short and unremarkable**, so that nothing else in it draws a flag.
- **Cover every language the rule is for.** A rule headed for a template that serves Python and TypeScript
  needs cases in both.

Then add real cases:

- **Copy them by line range, unedited**, with the scopes that enclose them, into an excerpt file made for the
  batch. Put a comment line naming the source file above each excerpt.
- **Do the copying with a small script that checks each range still holds the title it should.** Files shift
  while an experiment runs, and a range that has slid by one line yields a case that means something else.
- **Keep the share of violations near what real code has**, usually a quarter or less. A batch that is mostly
  violations teaches a reviewer to flag everything.

## The answer key

Keep it under `key/` in the experiment folder. No run ever sees it.

| Column | What goes in it |
|---|---|
| Number | Cases are numbered across batches, so a result can name one |
| The clause | The words in question, shortened |
| Label | Violation, Clean, or Boundary |
| Class | The kind of case: what it has in common with others |
| What backs it | The check that makes it clean, or why nothing does |

- **Boundary** is for a case the user would not write that way but would not flag in someone else's code.
  Neither a flag nor a pass counts as an error on it. What each arm does is recorded and not scored.
- After the table, list the clean cases by what each one stresses, the labels still waiting for the user, and
  your prediction for every arm.
- **The user confirms the whole table before the first run.** Clean labels need it most: a case you designed
  as clean carries your reading of the rule, and nothing in the runs will question it until the baseline
  flags it and the batch is already spent.
- **After each batch, add to the key file which predictions were wrong and which labels changed**, with the
  reason. Leave the old label visible beside the new one, so a reader can tell which results it affected.

To get a ruling on a doubtful case, show the user four things: the item split into its parts, what the code
actually checks, the closest cases they have already ruled on, and what each label would mean for the scoring.
Offer Boundary as the answer when they are torn. A ruling often exposes what the rule is really about, so
record the reasoning with the label.

## The task

`assemble.py` takes a task file of one or two sentences saying what to judge and what to leave alone:

```text
Task: decide whether any of these tests' names (the quoted title, or the function name) violate that guidance.
Use the test bodies only as evidence about the names; do not review the bodies themselves.
```

The reply format, which `assemble.py` adds, asks for the guidance sentence each finding relies on. Keep it. It
is the only way to tell a catch made by the new line from one the existing guidance was already making.

`assemble.py` pastes `AGENTS.md` from each arm unless told otherwise. When the guidance is split across files,
name each with its own `--guidance`, in the order the project-mode canary reports them loading, so the reviewer sees where one file ends
and the next begins.

## Building and running a batch

```bash
.claude/skills/test-guidance-wording/assemble.py --arms-dir <arms> --task-file <task.txt> --code <shown path>=<local file> --id batch1 --out-dir <experiment>/reviewing/inputs
.claude/skills/test-guidance-wording/run.py --mode pasted --folder <run folder> --arms base --runs 1 --input '<experiment>/reviewing/inputs/{arm}-batch1.txt' --id batch1 --results <experiment>/reviewing/results
.claude/skills/test-guidance-wording/tally.py --results <experiment>/reviewing/results --replies --id batch1
```

That first call to `run.py` is the single run that goes alone. After it, run the baseline's second run, then
the candidates:

- **In series**, one arm per call (`--arms a`), reading the replies before the next. To read only the run just
  made, pass `tally.py` its name (`--only a-batch1-run1`); `--fields guidance` cuts each finding to the sentence
  it cites. Neither needs a pipe through `grep`.
- **In parallel**, name every remaining arm in one call per batch, and start the calls for different batches
  together, each with a run folder of its own. Runs for one batch always share a folder, so the path the model
  sees is the same for every arm.

## Scoring

- **A flag is a hit only when its phrase is the labelled defect.** A flag on the same item for another reason
  is unrelated and is counted apart.
- **Attribute each hit** to the new line or to an existing sentence, from the guidance the reviewer quoted.
- **Compare each case with the baseline**:

  | Baseline | Candidate | The case is |
  |---|---|---|
  | Missed | Caught | Gained |
  | Caught | Missed | Lost |
  | Caught | Caught | Kept, and not to the new line's credit |
  | Missed | Missed | Still open |

- **Count unrelated flags per run.** They are where two identical runs differ, which makes them the noise
  floor. A candidate that draws far fewer of them than the baseline may be crowding out other guidance.
- **Two runs that disagree on a labelled case** are reported as unstable. Do not average them.

## What a result usually means

| Result | Likely cause | Next move |
|---|---|---|
| The baseline flags a case labelled Clean | The label, more often than the guidance | Re-check the label with the user before reading anything into the arms |
| The baseline already catches a class | An existing sentence covers it | Read which sentence. The new line need not repeat it, and must not weaken it |
| A candidate loses a case the baseline caught | Its text grants an allowance the reviewer applied | Read the reviewer's reason, find the granting words, remove them |
| A candidate flags a clean case | Its criterion is about something other than what the user ruled on | Rewrite the criterion, not the examples |
| A candidate misses the defect in an unnamed phrasing | Reviewers read its examples as the definition | Define the thing first and give examples second |
| Every arm misses a class | Nothing in the file speaks to it | Ask the user whether that class is worth a rule at all |
| Two candidates agree on every case | The extra words in the longer one do no work here | Take the shorter, and say that the cut sentences had thin coverage |

## The breaker batch

Once one wording leads, try to break it before recommending it. Aim cases at:

- **Phrasings its examples do not name**, both as violations and as clean cases.
- **Cases its text covers literally but should leave alone**: the rule's own vocabulary in a place the rule is
  not about, or as the whole of what the item says.
- **Whatever was cut to shorten it.** Each sentence removed was guarding something.
- **A check added only to satisfy the rule.** If the rule asks for backing, write a case whose backing is
  there but could never fail on its own.

Write down which failure you expect. Run the baseline and the leading wording. Run an older or longer wording
only if the leader fails on a case that wording was meant to protect.

## Shortening a wording

Shorter guidance is read more reliably and costs every session less. Once a wording works, cut it to the
sentences that carried the criterion and rerun the batches. If no verdict changes, keep the short one, and
list what was cut and how few cases covered it.
