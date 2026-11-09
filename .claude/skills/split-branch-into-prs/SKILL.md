---
name: split-branch-into-prs
description: Plans how to split one large feature branch into small PRs that each land on main on their own, stacked on another layer only where the code cannot build or pass its tests without it, records the plan as a beads epic, and then guides building each layer and bringing the rest up to date after each merge. Use this whenever a branch or PR has grown too big to review in one piece, a reviewer balks at a PR's size, or the user wants to land work in pieces or talks about stacked PRs, even when they never say "split".
when_to_use: /split-branch-into-prs, "break this branch up", "split this PR", "this PR is too big", "carve a PR off this branch", "land this in pieces", "stacked PRs", a reviewer asking for smaller PRs, or a later session that builds one layer of a planned split or restacks after a layer merged.
user-invocable: true
allowed-tools: Bash(git fetch *), Bash(git merge-base *), Bash(git diff *), Bash(git log *), Bash(git show *), Bash(git rev-parse *), Bash(git status *), Bash(git switch *), Bash(git restore *), Bash(gh pr list *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr checks *), Bash(gh repo view *), Bash(bd *), Read, Write, Edit, Grep, Glob, AskUserQuestion
argument-hint: "<big-branch> [--base <branch>]"
---

# Split a big branch into PRs

Below, `main` stands for the branch the split lands on; `--base <branch>` names another one.

## Purpose

Take `<big-branch>`, typically dozens or hundreds of commits and thousands of lines, and plan a set of small
PRs that together land everything it holds. Each PR targets `main` on its own. Only when a layer's code cannot
build or pass its tests without another layer does its PR target that layer's branch instead: a stack made of
ordinary branches and ordinary PR bases. No stacking tool, and none of GitHub's stacked-PR features, which cost
more than they save.

The work has three phases, usually in different sessions:

1. **Plan**, this file: survey the branch, draw the layers and their dependencies, and record the plan as a
   beads epic with one child per layer, specific enough that a later session can build any layer without
   re-deriving the analysis.
2. **Build a layer**: read `.claude/skills/split-branch-into-prs/references/build-layer.md` once the user has
   authorized building one.
3. **After a layer merges**: read `.claude/skills/split-branch-into-prs/references/after-merge.md` to bring
   its dependents and the big branch up to date.

Building, committing, pushing and opening PRs each need the user's explicit go-ahead. A plan, even an approved
one, is not that go-ahead.

## Principles

- **Plan from the final state, not from the history.** With squash merges nobody reads the branch's commits
  again. The log is still the best map of where the seams are and of which intermediate shapes were once
  coherent.
- **Independent by default.** A layer targets `main` unless it cannot build or pass its own tests without
  another layer's code. Two layers that merely touch the same file both target `main`; whichever merges second
  takes `main` in afterwards. Stacking buys a clean review diff at the price of a restack after every merge
  below it, so it has to earn its place.
- **Stacks stay shallow.** Each level adds one more restack round for each merge beneath it. Several short
  stacks hanging off `main` beat one tall one, and their reviews run in parallel.
- **Every layer stands on its own.** Its tests, coverage threshold, lint, type checks and CI pass without the
  layers above it. A strict coverage threshold means code lands together with the tests that execute it, which
  forces *interim forms*: simplified versions of shared functions that a later layer completes.
- **Recorded test artifacts pin test identity.** VCR cassettes, snapshots and similar files are keyed by test
  module, class and function name, and are never hand-edited. A recorded test moves whole and unrenamed, with
  its recording beside it. Test bodies may be carved; test names may not.
- **Destructive behavior lands with its guards.** A layer that can delete or overwrite something on a live
  system includes the refusals that make it safe. `main` never holds an unguarded version.
- **`main` keeps working between merges.** The feature only becomes usable once its last layer lands; until
  then every intermediate state is inert or safe.
- **The big branch stays the source of truth.** Layers are carved from its final tree, and whatever a layer's
  review changes is merged back into it, so later carves carry those changes without anyone re-applying them
  by hand.
- **History is never rewritten.** Branches are brought up to date by merging, never by rebasing or
  force-pushing: reviewers link to commits mid-review and the comment tooling posts commit URLs, which a rebase
  breaks, and squash merging erases the merge commits anyway.
- **The final comparison is conceptual.** Fixes and improvements turn up along the way, found by you or by
  reviewers, so an exact match with the original branch is not the goal. Every behavior, test, TODO and doc of
  the branch lands somewhere, and every departure is recorded.
- **Only the carve is yours to make.** Mechanical work is part of building a layer: taking files, trimming
  hunks that belong to other layers, writing the interim forms the plan names, regenerating, resolving merge
  conflicts by the rules in the references, fixing lint. Anything that was not in the big branch, such as a
  fix a reviewer asked for, an improvement you spotted or a guard the layer turns out to need, is new work and
  goes through the team's TDD flow with the user: `/create-issues`, after which the user invokes `/red`,
  `/green` and `/refactor` in turn. The user agreeing that a change is a good idea is not a request to make it.
- **A plan is not authorization.** Never commit, push or open a PR on the strength of an approved plan. The
  user's own rules on commits and PRs win over any default here.

## Step 1: Survey the branch and the repository

Every phase uses `<big-branch>` as a local branch. When it is not one yet (a PR you have not checked out),
create it first with `git fetch origin <big-branch>:<big-branch>`.

```bash
git fetch origin main
git rev-parse <big-branch>                      # the tip this plan is made from; it goes into the epic
git merge-base origin/main <big-branch>
git diff --stat origin/main...<big-branch>
git diff --name-status origin/main...<big-branch>
git log --reverse --format='%h %s' origin/main..<big-branch>
gh pr list --head <big-branch> --state all      # an existing PR the split will shrink or replace?
gh pr checks <existing-pr>                      # is the branch's final state green?
```

With no PR, `gh pr checks` has nothing to show, so run the lint, type and unit checks at the tip yourself. A
layer cannot be greener than the code it is carved from, so the plan has to say which layer carries any
failure the tip has.

Then the repository's plumbing, because the later phases depend on it:

```bash
gh repo view --json deleteBranchOnMerge,squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
grep -n -A4 'pull_request' .github/workflows/*.y*ml    # a `branches:` filter means no CI for PRs whose base is a layer branch
```

- **Merge method and branch deletion.** `.claude/skills/split-branch-into-prs/references/after-merge.md`
  assumes squash merges with the head branch deleted on merge; when a head branch is deleted, GitHub retargets
  every open PR that had it as base to the merged PR's base. With other settings, adapt that procedure before
  planning any stack.
- **AI reviewer.** Whether it reviews drafts and PRs whose base is not the default branch (for CodeRabbit,
  `reviews.auto_review.drafts` and `reviews.auto_review.base_branches` in `.coderabbit.yaml`). A stacked PR is
  a draft with a non-default base until its parent merges, so without both settings it gets no review until
  then unless someone triggers one by hand.

Then read:

- **Production code.** Read the diff of every production file in full. This is where layers get carved.
- **Test files.** Outline each changed test file, for example with `grep -n -E '^(class |    def test_|def )'`,
  to see which tests exercise which slice.
- **Shared test helpers and fixtures.** They almost always split across several layers.
- **Dependency, lock, version and generated files.**
- **Fixture usage.** For each fixture directory the branch adds, find the test files that reference it.
- **Intermediate shapes in history.** Look for places where the branch's history already held a simpler
  version of something: `git show <sha>:<path>`. A shape that was once committed and coherent is the best
  interim form to reuse.
- **Commits already landed.** A commit in the log may already be in `main` by content, squashed through an
  earlier PR. `git merge-base --is-ancestor <sha> origin/main` tells whether the commit itself is; the
  three-dot diff tells what remains. Plan from the diff, and use the log only as the map.

## Step 2: List the constraints that shape the slicing

- **Coverage threshold.** Which new code is exercised only by tests that belong to a later slice?
- **Recorded artifacts.** Which tests carry cassettes or snapshots, and where do those files live?
- **Generated code.** Which slices change an API contract? Those need the schema and generated clients
  regenerated. Check each regeneration's diff for side effects on unrelated files.
- **Lock files and anything hashed from them.**
- **Version and release.** Does the branch bump the version? Does the release workflow refuse a version whose
  tag already exists? If so, a bump in the last layer blocks anyone from releasing a half-landed feature.
- **CI and E2E.** Which suites need live services? Can E2E run locally? Does it need a fresh build first? A
  stale build gives false greens.
- **Team rules.** Read the repository's agent instructions (`AGENTS.md`, `CLAUDE.md` or the like) for who may
  commit, push and open PRs; the PR template and commit message conventions; the TODO policy; and the shell or
  hook restrictions that shape how commands are run.

## Step 3: Find the seams and draw the dependency graph

Typical layers. The tag says where each usually goes; the branch decides.

1. **Dependency bumps.** Independent, and small enough to ride along with the layer that needs them.
2. **Vocabulary renames of existing surface**, such as config keys, fixtures and TODOs. Independent. Keep them
   mechanical with types unchanged; a later layer changes the types.
3. **DRY refactors of existing test suites** that the feature's tests lean on later. Independent.
4. **Behavior-preserving refactors of existing production code** the feature plugs into. Independent. Check
   that some test covers any new invariant such a refactor introduces.
5. **Design docs and ADRs**, ahead of the code, so the design is reviewed before its implementation.
   Independent.
6. **Config or schema, and its validation.** Usually independent: parsed at this layer, read by nothing yet.
7. **The persistence, repository or client layer**, with its recorded tests. Independent, or stacked on 6.
8. **The read path.** Usually stacked on 7.
9. **The write path together with its guards.** Usually stacked on 7 or 8.
10. **Reporting, preview or UI**, plus the version bump. Stacked on whatever it displays.

For every layer, record its **base**: `main`, or the one layer it cannot do without, with the reason (the
function, fixture, schema or test it needs). The test for "cannot do without" is concrete: would the layer
build and pass its own tests, coverage included, on `main` alone? If yes, it is independent, whatever files it
shares with others. When the overlap with another independent layer is so large that the second diff would be
unreadable until the first merges, say so in its notes and let the user settle the merge order; stacking is
still not the answer.

A layer that needs several other layers cannot stack on all of them. Record every one of them as a
dependency, and build it only once at most one of them is unmerged: stacked on that one, or on `main` when all
have merged. Until then it waits, and its child says so.

Give each layer one reviewable purpose, and put foundations first. A layer that adds code with no callers yet
is fine, as long as its tests cover the code and its PR says which layer calls it.

## Step 4: Plan each layer's carve

For every layer, record:

- **Branch name and base.** Name layers so they sort together without nesting under the big branch's name:
  `refs/heads/<big-branch>` and `refs/heads/<big-branch>/<slug>` cannot coexist, so use `<big-branch>--<slug>`
  or a plain slug.
- **Files to take whole** from the big branch with `git restore --source=<big-branch> -- <paths>`.
- **Files to carve by hand**, meaning files that several layers share. Keep the final file's ordering, so a
  later layer only inserts or edits code and never moves any.
- **Interim forms.** Name each simplified signature or function body a layer needs for coverage, and the later
  layer that completes it.
- **Interim spots.** The lines to point out to reviewers with inline PR comments: simplified forms, code
  landing early for a later layer, and comments that name code arriving later.
- **What moves with the layer**: tests, fixtures, cassettes and snapshots.
- **Regeneration steps**, the verification commands, and Given/When/Then acceptance criteria.

## Step 5: Ask the user before creating anything

Use AskUserQuestion, at most four questions per call, recommended option first:

- **Granularity.** Your recommended set of layers, plus a finer option that splits the risky layers and a
  coarser one with fewer PRs.
- **The dependency graph.** Which layers are independent and which are stacked on which. The user may know a
  dependency the code hides, or want two layers folded together.
- **Publishing.** How far to go: plan only, commit locally, or push and open PRs. Assume plan only until told
  otherwise. Pushing a layer includes folding it back into the big branch and pushing that too (see
  `.claude/skills/split-branch-into-prs/references/build-layer.md`). Independent PRs may open ready for review
  or as drafts; a stacked PR stays a draft until its base is `main`.
- **The existing PR.** When the branch already has a PR, prefer keeping it as the final layer: its diff shrinks
  as layers merge, and its review threads and issue link survive. Offer closing it with a pointer when that is
  impractical, for example when what remains needs splitting again or its threads are too noisy to follow.

Also settle:

- version bump placement, first or last;
- placement of docs and ADRs;
- whether a layer may hold several logical commits;
- how deviations from the branch are handled (the defaults are in the principles: mechanical ones merge back
  into the big branch, and anything new goes through the TDD flow with the user).

Expect answers to reshape the plan. When the user tells you to skip the questions, take the recommended
options, write them into the epic's decisions as unconfirmed defaults with the date, and repeat them in your
closing message so the user can overrule any of them before a layer is built.

## Step 6: Create the beads epic

The plan lives in beads, the session-scoped tracker. A rebuilt environment loses it, which is acceptable
because a split should not take long. Reviewers never see it, so anything they need goes into PR bodies
instead (see `.claude/skills/split-branch-into-prs/references/build-layer.md`).

- **Create the epic.** Write the long text to files first, then run
  `bd create "<title>" -t epic -p <priority> --external-ref <ticket> --body-file <description.md> --design-file <design.md> --acceptance "<criteria>" --json`.
  - **Description:** the goal, the source branch, the tip SHA the plan was made from and the PR, the layers
    with their bases, the user's dated decisions, and a status line.
  - **Design:** how a layer is built, committed, pushed and opened; what happens after a merge; how deviations
    flow, and that new work goes through `/create-issues` and the user's `/red`, `/green` and `/refactor`;
    constraints that apply to every layer; what `main` holds between merges.
  - **Acceptance:**
    - the conceptual comparison with the branch holds;
    - every layer is green on its own;
    - every PR targets `main`, or its parent layer's branch while stacked, names its parent in its reviewer
      notes, and no stacked PR is ready for review while its base is a layer branch;
    - the interim spots carry inline comments;
    - the original PR is the final layer, or closed with a pointer to the series.
- **Create one child per layer** with `--parent <epic>`; the title is the PR title.
  - **Description:** the carve instructions from Step 4.
  - **Acceptance:** Given/When/Then criteria.
  - **Notes:** the branch name and base; talking points for each section of the PR template; the interim
    spots. Later, `bd update <id> --append-notes "<text>"` adds the PR, head SHA, review, and any deviation a
    later layer must carry forward.
- **Chain only the real dependencies** with `bd dep add <stacked layer> <its parent>`, which reads as "stacked
  layer depends on parent", once per parent for a layer that needs several. Confirm the children with
  `bd list --parent <epic>` and each chain with `bd dep tree <base layer> --direction up`; the tree from the
  epic itself stays empty, because children hang off it by parent-child links, not blocking ones. Check that
  `bd ready` lists every independent layer, since each can be built and reviewed at once. A stacked layer
  drops out of `bd ready` until its parent closes, which happens when the parent merges; it is buildable
  earlier, as soon as the parent is pushed, and
  `.claude/skills/split-branch-into-prs/references/build-layer.md` says how to tell.
- **Relate the epic to earlier work** with `bd dep relate <epic> <earlier epic>`.
- **Export after every create, update or dependency change** with
  `bd export -o <repo-root>/.claude/.beads/issues-dump.jsonl`.
- **Pass acceptance and notes inline.** They have no file flag, so quote them with care.

## Planning pitfalls

- **Plan for deviations.** A zero-diff final comparison is unrealistic. Record every deviation on the layer's
  child, and merge the layer branch back into the big branch so the next carve carries it.
- **Take a refactor's motivation from the original commit messages.** Do not reconstruct it. When the user
  asks why a change exists, quote the source.
- **New invariants need a test.** When a refactor introduces one, check that some test covers it. A long
  round-trip E2E through the primary happy path often covers it best, with a generic title and a phase comment
  before each step.
- **Code generators can rewrite unrelated files**, for example by stripping license or template headers. Plan a
  review of the generated diff into every layer that regenerates.
