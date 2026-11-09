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
gh pr diff <parent-pr> --name-only > parent-files.txt
git fetch origin main
git merge origin/main
```

Conflicts are expected in files the parent touched where this layer edited the parent's lines: completed
interim forms, moved code. The squash commit shares no ancestry with the dependent, so git sees two different
changes to the same lines. The dependent's side is right, because it already holds the parent's final content.

When every conflicted file (`git diff --name-only --diff-filter=U`) is in `parent-files.txt`, and
`git log --oneline $(git merge-base "$BEFORE" origin/main)..origin/main -- $(cat parent-files.txt)` shows only
the parent's squash commit, take the shortcut: `git merge --abort && git merge -X ours origin/main`. Otherwise
resolve by hand: the dependent's side for the parent-versus-dependent hunks, `main`'s side for anything else.
Resolving picks between versions that already exist; the moment a hunk would need new code, stop and take it
to the user as new work, which goes through the TDD flow named in the skill's principles.

A conflict on an **independent sibling** is different: it is this layer against a layer it was never built on,
and neither side alone is right. The big branch holds both, so resolve each hunk to the big branch's text,
then check that `git diff <big-branch> -- <file>` shows only changes belonging to layers not yet merged.

## 4. Verify

```bash
git diff "$BEFORE" HEAD -- $(cat parent-files.txt)    # empty after the shortcut; after a hand resolution, only main's unrelated changes
git diff "$BEFORE" HEAD --stat                        # anything else is what other PRs changed on main; usually nothing
git diff origin/main...HEAD --stat                    # the PR's diff as GitHub will show it: this layer's files only
```

The PR's diff should match `git diff "$PARENT_TIP" "$BEFORE"` hunk for hunk, apart from context changed by
unrelated commits on `main`. Nothing of this layer's own content may have moved, and nothing of the parent's
may remain. Then rerun the layer's checks, since `main` may have changed around it.

## 5. Push and update the PR

`git push`, plainly. The Files Changed tab is correct now; the Commits tab keeps listing the parent's commits,
which the squash left unreachable from `main`, and that is cosmetic. If the PR was a draft only because it was
stacked and the user says so, `gh pr ready <n>`. Trigger the AI reviewer when it needs that.

## 6. Grandchildren

Nothing is required: their base branch gained a merge commit, not a rewrite. Merging the parent into them when
convenient keeps them merged up for their own turn, and step 2 catches any that lag.

## 7. The big branch

Treat it as a dependent: the ancestry check, the merge, the shortcut under the same condition, the
verification, a plain push. When the big PR is kept as the final layer, GitHub retargeted it to `main` if its
base was the merged branch. After the merge, retarget it to the next top of the unmerged chain with
`gh pr edit <big-pr> --base <top-layer-branch>`, keeping it a draft while its base is a layer branch. Once every
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
- **`-X ours` silently drops `main`'s unrelated changes inside conflicting hunks.** The condition in step 3 and
  the checks in step 4 are what make it safe; skip neither.
- **GitHub's "Update branch" button is this merge without `-X ours`.** It fails on the expected conflicts, and
  when it succeeds the verification still has to run locally.
- **Never rebase or force-push to clean up the duplicated commits.** The duplicated view disappears on its own
  once the merge lands, and the rewrite would break every commit link in the review.
- **A dependent that lags its parent's tip** turns review fixes into conflicts that `-X ours` resolves the
  wrong way. Step 2 exists for that.
