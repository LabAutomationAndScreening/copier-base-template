# Build a layer

Read this when the user has explicitly authorized building a specific layer of a planned split. Re-read their
commit rules before every layer: "looks good" and "do layer N" authorize building and verifying, not
committing, pushing or opening a PR. `main` stands for the branch the split lands on.

## 1. Load the layer

`bd show <child> --json` gives the branch name, the base, the carve instructions, the interim spots and the
talking points. An independent layer is buildable from the start, and `bd ready` lists it. A stacked layer is
buildable as soon as its parent's notes record a pushed branch and an open PR, because the child is cut from
the parent's tip and reviewed against it; `bd ready` lists it only once the parent closes, which is after the
parent merges, so do not wait for that. A layer with several parents waits until at most one of them is
unmerged, then stacks on that one.

## 2. Create the branch

```bash
git fetch origin
git switch -c <layer-branch> origin/main              # independent layer
git switch -c <layer-branch> origin/<parent-branch>   # stacked layer, from the parent's current tip
```

Use the name the plan recorded. A name nested under the big branch's (`<big-branch>/<slug>`) cannot exist
while `<big-branch>` does, so plans use `<big-branch>--<slug>` or a plain slug.

## 3. Build it

- Take whole files from the big branch with `git restore --source=<big-branch> -- <paths>`.
- Carve shared files by hand toward the final file's ordering, so a later layer only inserts or edits code and
  never moves any.
- Write the interim forms the plan names, and leave the comments that name the layer completing them.
- Run the layer's regeneration steps, and read the generated diff for rewrites of unrelated files.
- Then `git diff <base-of-this-layer>` (`origin/main` or the parent branch) and account for every hunk. A hunk
  that belongs to another layer rode in with a whole-file restore: a sibling's unmerged change has to be
  trimmed out, while a change the big branch picked up from an already merged or parent layer's review is
  correct and stays.
- Stop at the edge of the carve. A missing guard, a better name, a bug you notice: note it on the layer's
  child and raise it with the user. If they want it, it goes through `/create-issues` and the user's `/red`,
  `/green` and `/refactor`, not into this build.

## 4. Verify

- Lint and type checks the way CI runs them, for example `pre-commit run -a`.
- The full unit suite with coverage.
- E2E against a fresh build for every flow the layer touches; a stale build reports false greens.

A hook that checks for a dirty tree fails when run by hand on uncommitted work. Check whether it skips itself
inside a real commit before chasing it.

## 5. Commit, when authorized

Plain, small commits are enough: the squash merge erases them, and reviewers link to them mid-review, so
there is nothing to gain from curating them and something to lose from rewriting them. After the last commit,
`git status --porcelain` is empty, so the tip is the tree you verified.

## 6. Push, when authorized

`git push -u origin <layer-branch>`. Never with force, here or later.

## 7. Open the PR, when authorized

Write the body from the repository's PR template. Its reviewer-notes section, the one that asks about merge
order, says how this PR relates to the split, since the plan itself is invisible to reviewers:

- Independent: "Part of splitting #<big-pr> (`<big-branch>`) into reviewable pieces; independent of the other
  parts."
- Stacked: "Part of splitting #<big-pr>. Stacked on #<parent-pr> (`<parent-branch>`): this PR's base is that
  branch, so the diff shows only this layer. It stays a draft until #<parent-pr> merges and GitHub retargets
  it to `main`; then it is brought up to date by merging and marked ready."

```bash
gh pr create --base <main or parent-branch> --head <layer-branch> --title '<title>' --body-file <body.md> [--draft]
```

A stacked PR is always a draft: the merge button on a PR whose base is a layer branch merges into that branch,
skipping `main`'s protections and merge queue, and a draft cannot be merged. An independent PR opens as the user
chose. If you may not open PRs yourself, hand the user the command.

If the AI reviewer skips drafts or non-default bases (checked in the plan's Step 1), trigger a review by hand,
for CodeRabbit with a `@coderabbitai review` comment, or tell the user none will come until the retarget.

## 8. Point out the interim spots

Post one review with the `COMMENT` event and one inline comment per spot. Use the repository's comment-posting
skill when it has one (`post-review-findings` posts a review of inline comments; `pr-comments` posts replies and
top-level comments), so the attribution conventions hold. Without one:

- set `commit_id` to the PR's head SHA, and give each comment `path`, `line` and `side: RIGHT`;
- post with `gh api --method POST repos/<owner>/<repo>/pulls/<n>/reviews --input review.json`;
- confirm the anchoring with `gh api repos/<owner>/<repo>/pulls/<n>/comments`.

## 9. Fold the layer back into the big branch

This gives the big branch an ancestry that includes the layer. Later review fixes then flow into it by merge,
the big PR can show only the remaining work when it is kept as the final layer, and the shortcut in
`.claude/skills/split-branch-into-prs/references/after-merge.md` becomes safe. The merge is a commit on the
big branch, so it needs the same go-ahead as any other commit.

```bash
git switch <big-branch>
git merge origin/main           # first, so that the layer's merge below adds nothing but ancestry; resolve any conflict by hand
BEFORE=$(git rev-parse HEAD)
git merge <layer-branch>        # conflicts only at the interim forms, where the big branch's version wins
git diff "$BEFORE" HEAD         # must be empty: the big branch's tree is unchanged
```

`git merge -X ours <layer-branch>` is acceptable for the second merge, because the layer was carved from this
very tree and carries no review changes yet. If the diff is not empty, the layer holds something the big branch
does not: either the carve is wrong, so fix the layer, or the change is wanted, so keep it and record it as a
deviation on the layer's child. Push the big branch with a plain push; this is part of pushing the layer.

When the big PR is kept as the final layer and the unmerged layers form one chain, retarget it to the top of
that chain with `gh pr edit <big-pr> --base <top-layer-branch>` and mark it a draft while its base is a layer
branch. Its Files Changed tab then shows only the remaining work. With several independent layers still open,
leave its base on `main`; it shows all of them until they merge.

## 10. Record

```bash
bd update <child> --status in_progress --append-notes "branch <layer-branch>, base <base>, PR #<n>, head <sha>, review <id>" --json
bd export -o <repo-root>/.claude/.beads/issues-dump.jsonl
```

## 11. While the layer is in review

- **Review fixes** are new work unless purely mechanical (a typo, a lint fix, a rename): each goes through
  `/create-issues`, then the user's `/red`, `/green` and `/refactor`, and lands as commits on the layer branch,
  pushed plainly. After each, merge the layer branch into the big branch again. Now a conflict can be real: a fix touching a line a later layer also edits is merged by
  hand, applying the fix into the big branch's version. `git diff <before> HEAD` on the big branch must show
  only the fixes.
- **Stacked children** merge the parent branch (`git merge <parent-branch>`) so that each stays merged up to
  its parent's tip. `.claude/skills/split-branch-into-prs/references/after-merge.md` checks
  `git merge-base --is-ancestor <parent-tip> <child>` before it takes any shortcut, and a child that lags turns
  the parent's fixes into conflicts resolved the wrong way.

## Pitfalls

- **Agreement is not authorization.** The user calling a reviewer's suggestion or your idea good does not
  start the work; `/create-issues` and the user's `/red`, `/green` and `/refactor` do.
- **The merge button on a stacked PR merges into the parent branch.** Drafts cannot be merged, which is why
  stacked PRs stay drafts until GitHub retargets them to `main`.
- **CI may not run for PRs whose base is a layer branch**, when the workflow filters `pull_request` by branch.
  The plan's Step 1 checks; if filtered, the layer's checks run locally and the PR says so.
- **The AI reviewer may skip drafts or non-default bases.** Trigger by hand or warn the user.
- **A nested branch name fails to create** while the big branch exists, with "cannot lock ref".
- **Whole-file restores carry every layer's changes to that file.** The diff review in step 3 is where
  siblings' unmerged changes get trimmed out.
- **Hooks that only fail on manual runs** and **generators that rewrite unrelated files** cost time when
  mistaken for real failures. Read the hook, read the generated diff.
- **E2E against a stale build reports false greens.** Rebuild before every E2E run.
