---
name: comment-audit
description: Audit source comments added on the current branch before pushing — classify each why-not-what, review every one with the user (keep/drop/edit), apply decisions, then stamp approval and push. Invoked when the comment-gate hook reports un-audited comments on a push, or on demand via /comment-audit.
user-invocable: true
allowed-tools: Bash, Read, Edit, AskUserQuestion
---

# Comment Audit

## Purpose

Aggressively review comments that have been added to a given branch/PR. Ensuring that you follow a YAGNI approach to comments is important: if the code itself can convey the information, it should.
You're goal is to catch source comments that should not ship:
comments that restate **what** the code does, comments that are really the **reply to a PR reviewer** committed into the source, etc. Only comments that explain a non-obvious **why** — a reason the code itself cannot convey — earn their place.

This skill is the reviewer that the gate (`comment-gate.py`, run as the PreToolUse hook) defers to. The
gate only detects that added comments exist; this skill does the judgment and the human escalation.

## Gate modes

The gate runs in one of three modes, set by `COMMENT_GATE_MODE` in the hook wiring
(`.claude/settings/hooks.jsonc`):

- **`warn`** (the template default) — the gate reports the un-audited comments and lets the push through.
  Running this skill is a recommendation, not a precondition.
- **`block`** — the push is refused until this skill stamps approval.
- **`off`** — the gate does nothing; `/comment-audit` still works on demand.

The workflow below is the same in every mode. In `warn` the stamp in Step 4 is not strictly required, but
still do it: it records that this HEAD was audited, and keeps the flow identical if the project later
moves to `block`.

## When to use

- Automatically: a `git push` where the gate reports un-audited comments (blocked in `block` mode, a
  warning in `warn` mode). Its message says to invoke `/comment-audit`.
- On demand: `/comment-audit`.

## Prerequisites

- A branch with commits ahead of its base (the gate resolves the base; see Step 1).
- `python3` available — the skill drives its two helper scripts, it does not re-derive detection by hand.

## Rules (read first)

- Work through **every** added comment with the user — do not silently keep or drop anything. A KEEP
  recommendation still needs the user's eyes.
- Do not hand-roll comment detection, the review blocks, or marker stamping. Detection and the verbatim
  `block` text both come from the `list` verb (Step 1); stamping from the `stamp` verb (Step 4). Calling
  them keeps the skill and the gate in exact agreement and stops you truncating or paraphrasing the
  comments under review.
- In `block` mode the only ways past the gate are this skill stamping the marker after a real review, or a
  human running `git push` themselves.
- Judgment lives here, in the full agent with repo context — the gate never classifies comments itself.

## Workflow

### Step 1 — Collect the added comments

Call the same scanner the gate uses — same per-file-type comment syntax, same multi-line coalescing:

```bash
python3 .claude/skills/comment-audit/comment-audit.py list <repo-root>
```

The range differs by how the audit was triggered, on purpose. The gate (a `git push`) audits only the
*outgoing* commits — the upstream's merge-base — so it re-reviews just what each push newly adds. This
manual `list` verb instead audits the **whole branch against its fork point** (the closest other
remote-tracking branch, falling back to `origin/main`), so `/comment-audit` still finds every comment on a
branch that has already been fully pushed. `COMMENT_GATE_BASE` overrides both. A `base == head` result
therefore means the branch adds nothing over its fork point — genuinely nothing to audit.

It prints JSON: `{ base, head, gitDir, comments: [{ file, start, end, raws, kind, block }] }`.

- `raws` — each comment (or docstring) line verbatim.
- `start` / `end` — real source line numbers.
- `kind` — `comment` or `docstring`. Python docstrings added in the range are included (extracted via the
  AST), so narrative docstrings that merely restate the code get audited too; judge them on the
  docstring-appropriate bar in Step 2.
- `block` — the ready-made Step 3 review text: the comment quoted verbatim from the HEAD blob with real
  line numbers and its surrounding code (docstrings with the def/class owner line above, inline comments
  with the code below). Use this in Step 3 as-is; never re-transcribe a comment yourself.
- `gitDir` — where the approval marker is stamped in Step 4.

Use `comments` as the audit set. If it is empty, tell the user there is nothing to audit and stop (the
push will pass).

### Step 2 — First-pass classify each comment

For each comment, read the surrounding code and form a verdict (KEEP / DROP / EDIT) with a one-line
reason. This is a recommendation only — the user decides every comment in Step 3.

- **KEEP** — explains a non-obvious *why*: a constraint, a gotcha, a reason for an unusual choice, a link
  to an external fact the code can't state.
- **DROP — restates what** — narrates what the next line or function already says (`// loop over devices`
  above a `for` over devices). Delete it.
- **DROP — reply text** — first-person acknowledgement or reviewer-directed narration ("Good call…",
  "as requested…", "the active-tile styling is covered by the screenshot"). Belongs in the PR reply, not
  the code. Delete it.
- **DROP — historical narration** — describes how the code used to be or what changed ("previously X, now
  Y", "changed from…", "renamed from…", "used to…", "no longer…", "was formerly…"). Git history is the
  sole record of what changed. Delete it — keep only a genuinely forward-looking *why* if one is tangled in.
- **Suppression directives** (`eslint-disable*`, `@ts-expect-error`, `@ts-ignore`, `prettier-ignore`,
  `biome-ignore`, `noqa`, `pylint: disable`, `type: ignore`, etc.) — the project requires a *why* on every
  ignore/skip. KEEP only if it carries a real reason: an inline `-- <why>` / trailing reason, or an
  adjacent comment explaining **why the rule is suppressed here**. If the reason is absent, empty, or
  circular ("disable the lint rule"), do **not** silently keep it — escalate to add a real reason or remove
  the suppression. A pointer like `-- see above` is fine only when the comment above actually explains why.

- **Docstrings** (`kind: docstring`) — a docstring earns its place as an API summary or a why. A one-line
  summary is fine; a multi-paragraph narrative that restates the function body line by line is the target.
  Apply the same bias-toward-why, but do not demand a docstring justify its existence the way an inline
  comment must — documenting a public function is expected.

**Bias toward DROP.** A comment survives only if you can state the specific non-obvious thing it tells a
reader that the code does not. "It's a helpful summary" is not enough.

### Step 3 — Review every comment with the user

Each comment in the Step 1 `list` JSON carries a `block`: the pre-rendered, verbatim, line-numbered
snippet. **Paste each `block` into chat exactly as it comes — never retype, summarise, ellipsis, or
shorten it.** The whole reason `block` is a ready-made string is so you copy it rather than transcribe it;
transcribing is where truncation creeps in. Do not route it through a scratch file — read the JSON and
emit the `block` value directly. Each block looks like:

```
<file>:<start>-<end>  [comment|docstring]
       <n>  <surrounding code line>
  >    <n>  <comment/docstring line, verbatim>
       <n>  <surrounding code line>
```

The comment/docstring lines are flagged with a leading `>`; a docstring is quoted with the `def`/`class`
owner line **above** it (what it documents), an inline comment with the code **below** it (what it
precedes).

Work in **rounds of four** (AskUserQuestion allows at most four questions per call): print the four
`block`s verbatim, each with your `→ <VERDICT>: <reason>` line, then ask the four questions. Each question
names the comment by `file:start-end` and its verdict. Loop until every comment has a decision — a large
audit is several rounds; do not skip any. One question per comment (**Keep / Drop / Edit**), options
ordered with your recommended verdict first.

- **Keep** — leave as-is.
- **Drop** — remove the comment line(s).
- **Edit** — rewrite it (usually: cut to only the why). Propose the rewrite; apply on confirm.

### Step 4 — Apply, commit, stamp, push

1. Apply the Drop/Edit decisions to the files.
2. If anything changed, commit it (one focused commit, e.g. `docs: cull comments that restate the code`).
   Follow the project's signed-commit rules.
3. **Stamp approval after the final commit.** Do not hand-write the marker — run the stamp verb, which
   records the current HEAD in `.comment-audit-ok` using the same git dir the gate reads. Run it *after*
   the last commit, or the recorded sha won't match HEAD and the gate reports again:

   ```bash
   python3 .claude/skills/comment-audit/comment-audit.py stamp <repo-root>
   ```

4. Push:

   ```bash
   git push
   ```

   The gate reads the marker, sees it matches HEAD, consumes it, and stays quiet. The marker is
   single-use: a later push that adds new comments is audited again.
