# After a layer merges

Read this when a layer's PR has merged. It assumes squash merges with the head branch deleted on merge, which
the plan's Step 1 checked. Everything here is done by merging; nothing is rebased or force-pushed, so every
commit URL in every review keeps working. `main` stands for the branch the split lands on.

## Who needs attention

- **Dependents**: every layer whose base was the merged branch (the children's notes say), and the big branch.
  Always, because their PRs now show the parent's commits and diff a second time.
- **Independent siblings**: only when GitHub reports a conflict on one, or its CI should rerun against the new
  `main`. Their base was `main` all along, so nothing is duplicated.

## 1. Confirm the retarget

For each dependent PR, `gh pr view <n> --json baseRefName`. GitHub retargets a PR to the merged PR's base when
the head branch is deleted; if the base is still the deleted branch, `gh pr edit <n> --base main`. Keep the PR
a draft through the steps below.

## 2. Get the parent's final tip

```bash
PARENT_TIP=$(gh pr view <parent-pr> --json headRefOid -q .headRefOid)
git fetch origin "pull/<parent-pr>/head"      # the commits stay fetchable through the PR ref after the branch is deleted
git merge-base --is-ancestor "$PARENT_TIP" <dependent-branch> && echo merged-up
```

A dependent that is not merged up never saw the parent's last review fixes. Merge `$PARENT_TIP` into it first
and resolve by hand, because the shortcut in step 3 assumes the dependent already holds everything the parent's
squash holds.

## 3. Merge `main` into the dependent

```bash
git switch <dependent-branch>
BEFORE=$(git rev-parse HEAD)
PARENT_FILES=$(mktemp)                        # outside the worktree, so the list can't clobber or join a commit
gh pr diff <parent-pr> --name-only | tr '\n' '\0' > "$PARENT_FILES"   # NUL-separated, so a path with spaces stays one argument
git fetch origin main
git merge --no-commit origin/main
```

Conflicts are expected in files the parent touched where this layer edited the parent's lines: completed
interim forms, moved code. The squash commit shares no ancestry with the dependent, so git sees two different
changes to the same lines. The dependent's side is right, because it already holds the parent's final content.
The same goes for lines git merges without a conflict: where this layer set a line back to its value from
before the parent, the dependent matches the merge base there, so git quietly takes the squash's value.

When `xargs -0 -r git log --oneline "$(git merge-base "$BEFORE" origin/main)..origin/main" -- < "$PARENT_FILES"` shows
only the parent's squash commit, take the shortcut: put back the dependent's version of every parent file the
merge changed, which settles both kinds at once.

```bash
xargs -0 -r git diff -z --name-only "$BEFORE" -- < "$PARENT_FILES" | xargs -0 -r git restore --source="$BEFORE" --staged --worktree --
```

Resolve any conflict left in other files by hand. Otherwise resolve by hand: the
dependent's side for the parent-versus-dependent hunks, both changes where another PR on `main` met this layer's
change (taking `main`'s side alone would drop this layer's), and in each parent file
put back any line of this layer's that the merge replaced without a conflict (`git diff "$BEFORE" -- <file>`
shows them). Resolving picks between versions that already exist; the moment a hunk would need new code, stop
and take it to the user as new work, which goes through the TDD flow named in the skill's principles.

A conflict on an **independent sibling** is different: it is this layer against a layer it was never built on,
and neither side alone is right. Resolve each hunk to `main`'s side plus this layer's own change. The big
branch shows how the two combine, but do not copy its hunk: it may also hold a change of a third layer not
yet merged. Then check that `git diff <big-branch> -- <file>` shows nothing but the changes of the other layers
not yet merged, each one missing here.

However the merge was resolved, show the user what it changed (`git diff --staged --stat`, and each hunk
resolved by hand) and run `git commit --no-edit` only once they say to commit: the approved plan is not that
go-ahead.

## 4. Verify

```bash
xargs -0 -r git diff "$BEFORE" HEAD -- < "$PARENT_FILES"     # empty after the shortcut; after a hand resolution, only main's unrelated changes
git diff "$BEFORE" HEAD --stat                        # anything else is what other PRs changed on main; usually nothing
git diff origin/main...HEAD --stat                    # the PR's diff as GitHub will show it: this layer's files only
rm "$PARENT_FILES"
```

The PR's diff should match `git diff "$PARENT_TIP" "$BEFORE"` hunk for hunk, apart from context changed by
unrelated commits on `main`. Nothing of this layer's own content may have moved, and nothing of the parent's
may remain. Then rerun the layer's checks, since `main` may have changed around it.

An **independent sibling** never held `$PARENT_TIP`, so its baseline is its own old base instead:
`OLD_BASE=$(git merge-base "$BEFORE" origin/main)`, still the base from before this merge, since `$BEFORE`
predates it. Its PR's diff should match `git diff "$OLD_BASE" "$BEFORE"` hunk for hunk, and the first check
above shows the merged layer's changes to the parent's files there, not nothing.

## 5. Push and update the PR

Once the user says to push, `git push`, plainly. The Files Changed tab is correct now; the Commits tab keeps listing the parent's commits,
which the squash left unreachable from `main`, and that is cosmetic. If the PR was a draft only because it was
stacked and the user says so, `gh pr ready <n>`. Trigger the AI reviewer when it needs that.

## 6. Grandchildren

Nothing is required: their base branch gained a merge commit, not a rewrite. Merging the parent into them when
convenient keeps them merged up for their own turn, and step 2 catches any that lag.

## 7. The big branch

Treat it as a dependent: the ancestry check, the merge, the shortcut under the same condition, the
verification, a plain push. When the big PR is kept as the final layer, GitHub retargeted it to `main` if its
base was the merged branch. After the merge, when the unmerged layers form one chain, retarget it to the top of
that chain with `gh pr edit <big-pr> --base <top-layer-branch>`, keeping it a draft while its base is a layer
branch; with several independent layers still open, leave its base on `main`, as in
`.claude/skills/split-branch-into-prs/references/build-layer.md`. Once every
other layer has merged, its base is `main`, its diff is the final layer, and it leaves draft when the user says
so.

## 8. Record

```bash
bd close <merged-child> --reason "Merged as #<pr>" --json
bd update <dependent-child> --append-notes "brought onto main at <sha> after #<parent-pr> merged; verified" --json
bd export -o <repo-root>/.claude/.beads/issues-dump.jsonl
```

Update the epic's status line too.

## Pitfalls

- **The same interim spots conflict at every level.** Squash commits carry no ancestry, so each merge of `main`
  into a dependent re-raises them. Expected, not a sign of a bad carve.
- **The shortcut's restore silently drops anything else `main` changed in the parent's files.** The condition in
  step 3 and the checks in step 4 are what make it safe; skip neither.
- **A clean merge is not a correct one.** Where this layer set a parent's line back, git takes the squash's value
  without a conflict. The shortcut puts it back; a hand resolution has to look for it.
- **GitHub's "Update branch" button is this merge without the shortcut.** It fails on the expected conflicts,
  and when it succeeds it may have taken the squash's value on such lines, so the verification still has to run
  locally.
- **Never rebase or force-push to clean up the duplicated commits.** The duplicated view disappears on its own
  once the merge lands, and the rewrite would break every commit link in the review.
- **A dependent that lags its parent's tip** turns review fixes into conflicts that the shortcut resolves the
  wrong way. Step 2 exists for that.
