---
name: copier-update
description: Update a copier-generated repo to a newer version of its template through the repo's own `task copier-update` / `task copier-update-from-ref`, answer any new template questions explicitly, resolve the .rej conflicts (project side wins unless certain), stop for the user on anything below high confidence, then commit the update with its mechanical fixes and each hand-made fix separately. Writes a JSON + HTML conflict-resolution report to <repo>/tmp/.
when_to_use: /copier-update, "copier update", "update the template", "pull in the latest template", "bump/sync/upgrade the copier template", "apply template changes", "the template has new questions", "resolve .rej files" or "copier conflicts", or `.copier-answers.yml` being out of date. Also invoked by the backport-copier-change skill for each repo down a template chain.
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Grep, Glob, AskUserQuestion
argument-hint: "[repo] [--ref REF] [--data KEY=VALUE ...] [--answers-file PATH] [--headless] [--pr]"
---

# Copier Update

## Purpose

Bring a copier-generated repo up to a newer version of its template without losing
repo-side changes, and leave an auditable trail: one report per update listing every
conflicted file, what was decided, how confident the decision is, and why.

Copier re-renders the template at the old and new versions, diffs them, and applies that
diff onto the repo with `git apply --reject`. Hunks that apply cleanly land silently;
hunks that collide with repo-side edits are written to `<file>.rej` and the repo's version
of that region is kept. So after the update the working tree already reflects "repo
wins". The job is to decide, per rejected hunk, whether the template change should be
carried in by hand.

## Helper

Mechanics go through one script. Below, `$CU` stands for
`.claude/skills/copier-update/copier_update.py`: run it as that bare path, written out in
full from the repo root, so the settings' allow-list for skill scripts matches.

```bash
$CU find-answers [repo]               # answers file, current/default branch, which update tasks exist
$CU refs [repo]                       # template's latest tag, default branch, 3 newest other branches
$CU new-questions [repo] --ref REF    # questions REF's copier.yml asks that are not answered yet
$CU update [repo] [--ref REF] [--data K=V ...]   # the repo's update task, --data forwarded and verified
$CU conflicts [repo]                  # `task prune-copier-rejects`, then the .rej files left
$CU capture-rej FILE.rej --root .     # report schema rejFile object, contents verbatim
$CU lint [repo]                       # uv sync each project, then the all-files hook run as CI runs it
$CU commit [repo] --draft D --message-file M [--approved FILE ...] [--skip HOOK ...]
$CU report [repo] DRAFT.json          # validate, write tmp/copier-update-report-*.json + .html
$CU pr [repo] --title T --body-file F   # push, then the draft PR command for you to run
$CU comment-report [repo] --report R     # once the PR is open, post the report on it
```

Every verb prints JSON. Do not re-derive by hand what a verb gives you, especially `.rej`
contents: retyping is where truncation and whitespace damage creep in.

In a GitHub Codespace, pass `--stored-gh-credentials` to `refs`, `new-questions`, `update`,
`pr` and `comment-report`. The injected `GITHUB_TOKEN` only reaches the codespace's own repo; the flag drops
it (and `GH_TOKEN`) so git and gh fall back to the credentials `gh auth login` stored.

## Arguments

| Argument | Effect |
|---|---|
| `<repo>` | repo path; default `.` |
| `--ref REF` | template tag, branch or SHA to update to; skips the Step 1 picker |
| `--data KEY=VALUE` | answer for a new template question; repeatable |
| `--answers-file PATH` | which answers file, when several exist |
| `--headless` | no questions at all; see **Headless mode** |
| `--pr` | after Step 7, open a draft PR and comment the report |

Any decision not covered by an argument is asked interactively, unless `--headless`.

## Rules (read first)

- **Never update on the default branch.** The `update` and `commit` verbs refuse outright.
  Step 0 creates a branch (or worktree) before anything touches the tree.
- **The repo's update task defines how copier runs.** `task copier-update` (latest tag) or
  `task copier-update-from-ref REF=...` hold the flags this template family relies on
  (`--conflict rej`, `--trust`, `--defaults`, the answers file). When every new question
  takes its default, `update` runs the task itself. When any answer has to be passed in, it
  runs the task's own `copier update` line (read with `task --dry`) with `--data` flags
  added. Never assemble a copier command by hand, never `copier recopy`, never
  `--force`/`--overwrite`.
- **Never hand-edit the answers file.** Copier writes it. An answer goes in through
  `--data KEY=VALUE` on the update, never through Edit, sed or a follow-up commit. To change
  an existing answer, rerun the update with `--data`.
- **Every new template question gets a decision before copier runs**, with a confidence,
  the same way a `.rej` resolution does (Step 2). Accepting the default is a decision too.
- **The repo side wins by default.** Carry a rejected template hunk in only when it is
  clearly template-owned boilerplate (CI, lint config, tooling versions, generated
  scaffolding) the repo never deliberately diverged from.
- **Anything below high confidence stops before the commit.** Record a `confidence` for
  every resolution. If any is `medium` or `low`, show the user both sides and your reasoning
  with AskUserQuestion and wait. `commit` refuses while such a resolution exists, unless it is
  passed with `--approved FILE` after the user decided.
- **`task prune-copier-rejects` runs before any triage.** It deletes `.rej` files whose
  target is unchanged in git (false positives, such as a hunk the repo already has).
- **One update commit, then one commit per hand-made fix.** The update commit holds copier's
  output, the resolved `.rej` conflicts and every mechanical fix: lock files, formatting,
  the devcontainer hash. When hooks still fail after the mechanical fixes, that commit skips
  exactly the hooks `lint` lists in `failed_hooks`, by id, and every other hook still runs.
  Each hand-made fix for a remaining hook failure is its own later commit, one fix per
  commit, so a reviewer going commit by commit sees each one. Never `--no-verify`.
- No `.rej` file, `.orig` file, conflict marker or `node_modules` path may be committed.

## Headless mode

For a routine or `claude -p`, nobody can answer. With `--headless` every point that would
ask takes a preset or aborts, never a guess:

| Decision | Headless rule |
|---|---|
| Dirty tree | abort |
| Several answers files, no `--answers-file` | abort |
| Branch vs worktree | branch, `chore/template-<slug>` |
| Target ref, no `--ref` | the latest tag |
| New question, no `--data`, default fits with high confidence | take the default |
| Any other new question without a `--data` | abort |
| Resolution below high confidence | abort before committing, report written |
| Hook failure needing a hand-made fix | abort after the update commit, report written |
| Hand off | `--pr` is implied; the PR is the review |

"Abort" means: stop, do not commit, leave the tree as it is, and say what was missing. A
failing verb also writes `<repo>/tmp/copier-update-aborted.json` (`{verb, error, at}`).

## Workflow

### Step 0: Preconditions

```bash
$CU find-answers <repo>
```

If `dirty` is non-empty, stop and ask whether to commit or set the work aside (copier
refuses a dirty tree). Do not stash on your own. `tasks` lists which of `copier-update`,
`copier-update-from-ref` and `prune-copier-rejects` the repo has; without them this skill
does not apply, so say so and stop.

If `branch` equals `default_branch` (or is `null`, detached HEAD), ask how to isolate the
work, then:

```bash
$CU branch <repo> --ref <TO_REF or latest>                      # a branch, in place (recommended)
$CU branch <repo> --ref <TO_REF or latest> --worktree <path>    # or a new worktree
```

With a worktree, every later `<repo>` is its `path`. Hooks in a fresh worktree or clone may
need the repo's `.claude/` node packages: install them there (`npm ci` inside `.claude/`)
rather than symlinking another checkout's. When this skill runs inside backport-copier-change,
the checkout and branch already exist, so skip this.

### Step 1: Pick the template ref

```bash
$CU refs <repo>
```

Skip this when `--ref` was given. Otherwise ask with AskUserQuestion, one question, noting
`current_commit` in the question text: the latest tag first (recommended, it is copier's own
default), then the default branch, then the recent branches (label `name`, description
`date: subject`). "Other" covers any ref not listed. Record it as `TO_REF`; for the latest
tag, the update runs `task copier-update` with no ref.

### Step 2: Detect new questions

```bash
$CU new-questions <repo> --ref "$TO_REF"
```

Always run this, even for a ref you expect to be a small change. For each entry in `new`,
decide the answer for this repo and record the decision and a confidence in
`<repo>/tmp/draft.json`. Each entry carries `has_default` and the question's `spec`, its
settings as written in copier.yml (`type`, `help`, `default`, `choices`, `when`, `secret`):

- **Has a default:** read `help`, `when` and the default, which may be a Jinja expression
  over other answers. Then check the repo: does what the question controls match how this
  repo works (its answers file, README, deployment and CI files)? Accept the default only
  when it clearly fits. If it clearly doesn't, pick the answer that does.
- **No default:** an answer has to be supplied. Work it out from the repo the same way.
- **Confidence:** `high` only when the repo itself settles the answer. Otherwise, ask with
  AskUserQuestion (at most four per call): `help` as the question, your proposed answer
  first and marked "(Recommended)" with the evidence in its description, then the default
  and the other `choices`. A question with no default always needs either a high-confidence
  answer or the user's.

Every answer that is not the default becomes a `--data name=value` flag. A question with no
default and no `--data` answer makes `update` refuse to run. For `secret: true` questions,
write the value to a `--data-file` under `<repo>/tmp/` instead, and delete it afterwards. If
`removed` is non-empty, tell the user: copier drops those answers.

### Step 3: Run the update

```bash
$CU update <repo> [--ref "$TO_REF"] [--data name=value ...]
```

Output: `{ command, copier_version, returncode, stdout, stderr, from_version, to_version,
answers_changed, conflicts }`, all of which go into the report. `command` shows which path
ran: `task ...`, or the task's copier line plus `--data`. `update` fails if a `--data` value
did not reach the answers file. On a non-zero `returncode`, read `stderr`, fix the cause and
rerun; never hand-apply part of an update.

Copier sometimes stages a change and then reverses it in the working tree (seen as `MM` in
`git status`, such as a footer removed in the index and restored on disk). Judge the
update by `git diff HEAD`, not by either half: those files have no net change.

### Step 4: Triage rejects

```bash
$CU conflicts <repo>
```

Read `prune_output`: it names each false positive it deleted. A non-empty
`conflict_markers` list cannot come from this update (it runs in rej mode), so stop and
ask. For each file in `rej_files`:

1. Read the `.rej` and the target. Work out, hunk by hunk, what the template changed and
   what the repo has there (`git log -p -- <target>` shows whether the divergence was
   deliberate). A common case: copier wrote the template's new block over the repo's own
   lines next to it, and the `.rej` is it refusing to add them back. Check `git diff HEAD`
   for the target's removed lines, and restore the repo's lines beside the template's.
2. Decide: keep the repo's version (`ours`), hand-apply the template hunk (`theirs` /
   `manual_merge`), and give the decision a confidence. `high` means you would not expect
   a reviewer to question it. Anything else is `medium` or `low`, and goes to the user now:
   show both sides verbatim with ours / theirs / merge options. A `manual_merge` that leaves
   out any template change, even one to a block the repo keeps as its own copy, is at most
   `medium`: its `description` names each template change carried and each left out, and
   its `reason` says why each was left out.
3. Apply the decision with Edit, run `$CU capture-rej <path> --root <repo>` **before**
   deleting the `.rej`, then delete it. Append the captured object and the decision
   (strategy, reason, confidence) to `<repo>/tmp/draft.json`.

Always add an answers-file entry (`is_answers_file: true`, `resolution_strategy:
"regenerated"`), so the draft is never empty on a clean update. Its `reason` lists each new
question's answer and why, except a `secret: true` question's value: the report is posted on
the PR, so for that question it says only that the value went in through `--data-file`, and
`description` doesn't name the value either. Its `confidence` is the lowest confidence among
those answers (`high` when there were none), so `commit` holds an unapproved answer exactly
as it holds an unapproved `.rej` resolution.

A clean update's draft, for the shape (field names and allowed values are in
`report.schema.json`; `commit` and `report` name any field that's wrong):

```json
{
  "resolutions": [
    {
      "filename": ".config/.copier-answers.yml",
      "is_answers_file": true,
      "description": "Copier moved _commit from v0.2.4 to v0.2.5; no answer changed.",
      "resolution_strategy": "regenerated",
      "reason": "Copier owns this file, and the update asked no new question.",
      "confidence": "high",
      "status": "resolved"
    }
  ]
}
```

### Step 5: Mechanical fixes, then the update commit

```bash
$CU lint <repo>
```

This first runs `uv sync --frozen` in every directory with a tracked `uv.lock` (`synced` names
the environments that changed, `sync_failed` any uv error), so the dependency-sync hook, which
fails whenever its own sync changes something, has nothing left to do; then it runs the repo's
hook runner on every file the way CI does (`git-dirty` skipped, since nothing is committed
yet). Hooks that rewrite files (`modifying_hooks`: formatters, lock files, the devcontainer
hash) are the mechanical fixes. Rerun until only `failed_hooks` that need a hand-made fix
remain, or none.

Write the commit message to `<repo>/tmp/commit-message.txt`, in the repo's commit style.
The subject names the template and version range, and the body has one line per resolved
file naming its strategy, then a line naming any mechanical fixes. Then:

```bash
$CU commit <repo> --draft <repo>/tmp/draft.json --message-file <repo>/tmp/commit-message.txt
```

It refuses while any resolution is below high confidence (rerun with `--approved FILE` for
each one the user decided), refuses a message whose first paragraph spans more than one line
(git would join it into one long subject; put a blank line after the subject), stages
everything except `tmp/`, and refuses staged `.rej`/`.orig` files, conflict markers and
`node_modules` paths. If hooks still block the commit, rerun it with one `--skip <hook id>`
per hook `lint` still lists in `failed_hooks`.

### Step 6: Hand-made fixes, one commit each

For each remaining `failed_hooks` entry: fix it, show the user the diff, and commit it on
its own once they approve, with a subject that says what and why (`fix(lint): drop unused
import the template update introduced`). When a fix's commit fails a hook that a later
fix repairs, commit it with `SKIP=<that hook id>` and name the hook and the later fix in the
message; never `--no-verify`, and never two fixes in one commit. Rerun `$CU lint` until its
`returncode` is 0, then run whatever else proves the resolved files work (the tests that
cover them, a template render) and record each command and its result for the report.

### Step 7: Write the report

Build the report from the draft to match `report.schema.json` (`schema_version: "1.0.0"`,
`operation: "copier-update"`):

- `project`: `git remote get-url origin`.
- `project_commit`: `{sha, name}` of HEAD before the update commit. `report` lists the commits after it as the
  update's own (`commits`, shown on the PR comment), so run `report` before anything else is committed.
- `copier`: `src_path`, `answers_file`, `from_version`/`to_version`, `copier_version`,
  `answers_changed` from the `update` output; `to_commit.name = TO_REF`; `conflict_mode: "rej"`.
- `resolved_by`: the model you are.
- `summary`: one paragraph naming the update commit and each fix commit.
- `resolutions`: the draft entries, each with `verification` from Step 6, an object:
  `{"commands": ["<each command run>"], "result": "passed"}` (`result` is `passed`, `failed`
  or `not_run`). `reason` is the why, not a restatement of the change.

```bash
$CU report <repo> <repo>/tmp/draft.json
```

On a misnamed or missing field, or a value that isn't one of its allowed ones, nothing is
written and stderr names each by its path in the JSON: fix the draft and rerun. Delete the draft afterwards, and give the user `html_url`. The report
is never committed. Publishing the `.html` as an Artifact uploads `.rej` contents and file
paths, so ask first.

### Step 8: Hand off

With `--pr`: fill the repo's PR template (`.github/pull_request_template.md`) into
`<repo>/tmp/pr-body.md`. Every section is answered for this update, never left as the bare
template. Then:

```bash
$CU pr <repo> --title "<title in the repo's PR title style>" --body-file <repo>/tmp/pr-body.md
```

It pushes the branch and prints the `gh pr create --draft …` `command`: run it. Once the PR is
open:

```bash
$CU comment-report <repo> --report <report .json>
```

posts the report on it as a comment. Do not merge.

Without `--pr`, do not push. Final message: the branch or worktree, `TO_REF` and the version
range, the update commit and each fix commit, `html_url`, and any `needs_review` entries.
