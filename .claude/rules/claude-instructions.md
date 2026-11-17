---
paths:
  - ".claude/skills/**"
  - ".claude/agents/**"
  - ".claude/commands/**"
---
# Claude Instructions

Conventions for writing and editing the instructions Claude follows for a task: skills, subagent definitions and
slash commands under `.claude/`.

## Where a skill tells the agent to write files

Choose each file's location by who reads it, and for how long:

- **A script, a later session, or the record of the run reads it** (a resume state file, a reply draft a script
  posts, a findings file, a report): `<repo_root>/tmp/`, which is gitignored. It survives the session, a `/clear`
  and a container rebuild.
- **Only the user reads it, while a question is open** (the context written for an AskUserQuestion):
  `/tmp/<short name>`, with the PR number, branch or repo in the name so sessions working on different things don't
  overwrite each other. The question gives the file's path, and a scratchpad path is too long to read there.
- **Only the agent reads it, within this session** (a draft, commit message or PR body passed to a script as an
  argument, a secret answers file, saved command output): the session's scratchpad. It is private and unique to the
  session, so parallel sessions can't collide; within one session, still name it by whatever the skill can run for
  more than once, such as a repo or a PR. A `/clear` starts a new session ID and so a new scratchpad, so nothing a
  resumed or cleared session needs goes there.

No environment variable names the scratchpad, so a script can't find it: a path a script builds on its own stays in
`<repo_root>/tmp/`, and a scratchpad file reaches a script only as an argument the agent passes.

Name the location explicitly in the skill's text. A bare `tmp/` reads as either the repo's `tmp/` or `/tmp`.
