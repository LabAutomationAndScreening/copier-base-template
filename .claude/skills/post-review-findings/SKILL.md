---
name: post-review-findings
description: Posts the findings of a /code-review run to the PR as one review, each finding attributed to the AI reviewer and cross-linked to the findings it relates to, so they can be worked through with /address-pr-comments. Run it right after /code-review finishes, in the same session.
when_to_use: /post-review-findings, "post the review findings", "post these findings on the PR", "put the code review on the PR".
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion, Skill
argument-hint: "[<pr number>] [--from <findings json or /code-review transcript>] [--commit <reviewed sha>]"
---

# Post Review Findings

## Purpose

Take the findings a `/code-review` run reported and post them on the PR, as one review the user approved, so that `/address-pr-comments` can work through them.

The findings are posted under the user's account, since that is the only identity available. Every finding carries a hidden `<!-- ai-review-finding id=F<n> ... -->` marker and a visible attribution line. The marker is what lets `/address-pr-comments` tell a finding that still needs a response apart from the user's own replies. Without it, a comment by the user counts as already addressed and is skipped.

## Conventions

- Run every script by its path (it has a shebang). Do not prefix it with `uv run python` or any other interpreter.
- Show every file path to the user as an absolute path, so it can be Ctrl+clicked in VS Code.
- `<repo_root>` is the output of `git rev-parse --show-toplevel`. Work files go in `<repo_root>/tmp/` (gitignored): `<findings_file>` is `<repo_root>/tmp/review-findings-pr<pr>.json`, and `<preview_file>` is `<repo_root>/tmp/review-preview-pr<pr>.md`. If `<findings_file>` already exists from an earlier run, ask before overwriting it.
- Each AskUserQuestion's `question` field carries everything needed to answer it. Context written before the call may never reach the user.
- Nothing is posted until the user has approved the preview in [Step 6](#step-6-get-approval). Posting is outward-facing and notifies the PR's participants.

## Step 1: Identify the PR and the reviewed commit

- **PR**: the argument, else the PR the `/code-review` was run against, else `gh pr view --json number` on the current branch.
- **Reviewed commit**: the commit the review actually read. Take it from `--commit`, else from the `/code-review` report (it usually names the head it reviewed). If the report does not say, ask the user. Do not assume the current PR head: the branch may have moved since the review started, and line numbers are only right for the reviewed commit.

## Step 2: Import the findings

Find the findings, in this order of preference:

1. **`--from <path>`** if the user passed one: a file holding the `/code-review` JSON array, or a `/code-review` agent transcript.
2. **The `/code-review` task notification in this conversation.** When `/code-review` runs in the background, its completion notification names an `<output-file>`. That is the agent's transcript, and its final message holds the findings array in a ```json block. Pass that path as `--from`, so the findings are copied byte for byte instead of retyped.
3. **The findings array shown in this conversation**, when there is no transcript (e.g. the review ran inline). Write the array exactly as reported, unedited, to `<repo_root>/tmp/code-review-findings-pr<pr>.json` and pass that.

If none of these exists (e.g. the conversation was compacted and the array is gone), ask the user for a file. Never rebuild findings from a summary.

```bash
.claude/skills/post-review-findings/post_review.py import --from <path> --pr <pr> --commit <reviewed sha> --out <findings_file> [--model <model id>] [--effort <level>]
```

Every posted comment opens with a line naming the model and effort level that ran the review, e.g. `🤖 AI code review finding by Claude Opus 5.5 (claude-opus-5-5) at max effort, reviewing 4fa7227`, so a reader knows from the first line that it came from an AI. A transcript records the model and effort, and `import` reads them. A bare array records neither, so pass `--model` with the model ID, and `--effort` if known. A `/code-review` run in this session, forked or inline, ran on this session's model, so that is your own model ID and effort level. Otherwise ask the user. Never guess.

This numbers the findings F1, F2, … (continuing after any finding IDs already on the PR) and writes `<findings_file>`:

```json
{
  "pr": 29,
  "reviewed_commit": "<full sha>",
  "summary": "",
  "findings": [
    {"id": "F1", "file": "...", "line": 53, "category": "...", "short_summary": "...",
     "summary": "...", "failure_scenario": "...", "related": []}
  ]
}
```

Fields of each finding (no need to read the script for them):

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | `F<n>`, unique on the PR |
| `file` | yes | path at the reviewed commit |
| `line` | no | line number in `line_commit`; `null` for a finding about the whole file |
| `line_commit` | no | the commit `line` refers to; defaults to `reviewed_commit` |
| `category` | no | shown next to the ID, e.g. `correctness` |
| `short_summary` | no | used in the review body's table; else the summary is truncated |
| `summary` | yes | the finding |
| `failure_scenario` | yes | concrete inputs or state, and the wrong result |
| `related` | no | `[{"id": "F9", "note": "..."}]`; every `id` must be in the file |

At the top level:
- `reviewer` is `{"model": "<model id>", "effort": "<level or null>"}`. Posting is blocked while `model` is `null`.
- `summary` is the review body's markdown.
- `posted` is written by the script; never set it yourself.

## Step 3: Findings outside the JSON

A `/code-review` report often lists more in prose: confirmed findings cut by its cap, cleanups, nits. Ask the user (one AskUserQuestion, listing them) whether to include them. For each one included, append an entry to `findings` with the next free ID. Find its exact `line` at the reviewed commit (`git show <reviewed sha>:<file>`). Use `null` only for a finding about a whole file, and keep the report's wording.

Do not include findings the report says were refuted or already fixed.

In the same question, ask whether any finding has been **settled since the review**: a decision the user made, or a fact the reviewer didn't know (e.g. "this was never deployed, so the migration can be regenerated"). The report can't know about these. Drop the settled ones, and mention them in `summary` so nobody re-raises them.

## Step 4: Relate the findings

Read every finding together and work out how they affect each other. Look for:

- **Same fix**: fixing one fixes the other.
- **Depends on**: one's fix changes whether another is still true or what its fix should be.
- **Conflict**: their fixes pull in different directions.
- **Obviates**: fixing one makes the other moot.

Record each relation in the `related` list of **both** findings, with a `note` written from that finding's side, e.g. on F15: `{"id": "F1", "note": "If F1 adopts validate_strings=True, the untyped table becomes necessary and this comment becomes true."}`. Use the relations the report states first, then add your own.

Set `summary` (the review body, markdown) to:
- a short suggested order for working through them, root causes first;
- the groups of related findings;
- anything the report checked and ruled out, in one line each, so nobody re-raises it.

Do not put findings themselves in `summary`. Every finding must be its own comment so it can be replied to and resolved.

## Step 5: Plan and preview

```bash
.claude/skills/post-review-findings/post_review.py plan --findings-file <findings_file> --preview <preview_file>
```

It prints the plan as JSON and writes `<preview_file>`: the review body and every comment exactly as they would be posted. Nothing is posted. Per finding, the plan gives:

- `placement`:
  - `line`: an inline comment.
  - `file`: a file-level comment, because the file is in the PR but the line is outside its diff hunks.
  - `pr_comment`: a top-level PR comment, because the file is not in the PR at all.
- `line_at_anchor`: the line the comment will sit on.
- `changed_since_review`: the code at that line changed after the reviewed commit, so GitHub will show the comment as outdated. The finding may already be fixed.
- `attention`: a problem that blocks posting.

At the top level, the plan gives:
- **`anchor_commit`** and **`reviewed_commit_in_pr`**: if the reviewed commit is still in the PR, the review is pinned to it and no line is recomputed. If the branch was rewritten, the review is anchored to the PR head and each line is mapped forward. A line inside changed code cannot be mapped and gets an `attention`.
- **`visibility`**: if `PUBLIC`, check every finding for names of, links to or quotes from private repositories and anonymize them (see AGENTS.md).
- **`blocking_problems`**: everything that must be fixed before `post` will run.

Resolve every `blocking_problems` entry by editing `<findings_file>`, then re-run `plan`:
- **An unmappable line**: find the code at `anchor_commit`. Set `line` to it and `line_commit` to `anchor_commit`, or drop the finding if it no longer applies.
- **An existing pending review**: the user must submit or discard it in the GitHub UI. GitHub allows one pending review per person per PR.
- **A finding ID collision**: renumber.

For each finding with `changed_since_review: true`, check whether the current code already fixes it. Bring those to the user in Step 6 as candidates to drop.

## Step 6: Get approval

Tell the user the absolute path of `<preview_file>`. Then ask with AskUserQuestion. The `question` field holds:
- the PR number and `anchor_commit`;
- a table of each finding's ID, placement and location;
- the findings that look already fixed, with your evidence;
- the relations you added that the report did not state;
- then: "Post this review?"

Options:
- **Post**: go to Step 7.
- **Edit first**: the user edits `<findings_file>`, or tells you what to change. Re-run Step 5 and ask again.
- **Cancel**: post nothing, and leave `<findings_file>` in place.

## Step 7: Post

```bash
.claude/skills/post-review-findings/post_review.py post --findings-file <findings_file> --anchor <anchor_commit>
```

`<anchor_commit>` is the one the approved question showed.

The script:
1. Re-runs the plan and refuses if anything blocks posting, or if its `anchor_commit` is no longer `--anchor`.
2. Creates a pending review on `anchor_commit`, so nothing is visible and no notifications go out.
3. Adds each finding as a thread, then posts `pr_comment` findings as top-level comments.
4. Fills in the links between related findings now that their URLs exist.
5. Submits the review as a `COMMENT`, so there is one notification.

On success it prints the review URL and each finding's URL, and records them under `posted` in `<findings_file>`. The script refuses to post that file again.

If the plan changed between approval and posting (e.g. someone pushed, moving the anchor or making a line unmappable), the script stops. Go back to Step 5.

### If posting fails

The script reads the review's state before cleaning up:
- **Still pending:** it deletes the review and any PR comments it created. The PR is as it was, so fix the cause and post again.
- **Submitted:** GitHub can apply a submit and still return an empty response. The script reports success and records `posted`.
- **Unreadable:** it deletes nothing and says so.

When it reports an error:
1. Show the user the script's output verbatim.
2. Find what is actually on the PR by reading its threads with the **pr-comments** skill (Skill tool), as its Read section says. Each posted finding has its `ai_review.finding_id`.
3. If some findings are on the PR and some aren't, run `plan --findings-file <findings_file> --resume --preview <preview_file>`. It skips findings already on the PR (`already_posted`) and lists the earlier comments it will edit to link the new ones (`will_edit_posted_findings`; GitHub marks those edited).
4. Get approval as in [Step 6](#step-6-get-approval), then run `post --findings-file <findings_file> --anchor <anchor_commit> --resume`.

Do not write your own repair script or call `gh api` directly. `gh api` is not allowed for agents, and the script's checks (pending reviews, ID collisions, links in both directions) would be skipped.

## Step 8: Report

Give the user:
- the review URL;
- the number of findings posted, by placement;
- anything you dropped or left out, and why;
- the next step: `/address-pr-comments <pr>`.
