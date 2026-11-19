# Project Structure

What this repository is and how it is laid out is described in a rule file the repository owns under `.claude/rules/`, which loads alongside this file. This file is the same in every repository generated from this template chain, so guidance for a single repository never goes here (see Memory and Rules).

# Code Guidelines

Rules for writing code and tests live in `.claude/rules/*.md`. Each file's `paths:` frontmatter lists the files it governs, and Claude Code loads the file when you read or write one of them. That can come too late, or not at all: a rule for a file you are creating loads only after the first write, and no rule loads for code you see only through a diff or other command output (as in a review), or for files in another checkout, where that checkout's own `.claude/rules/` apply. In those cases, first read the rule files whose `paths:` match the code.

# Agent Implementations & Configurations

## Memory and Rules

- Before saving any memory or adding any rule, explicitly ask the user where it belongs: (1) every project: a change to the template that owns the file, carried there with the backport-copier-change skill, either in `AGENTS.md` (guidance that applies whatever files are open) or in the `.claude/rules/` file whose `paths:` covers the code it governs; (2) this project only: a rule file this repository owns under `.claude/rules/` (one that `.config/.copier-managed-files.json` does not list), with `paths:` frontmatter when it governs particular files, and never an edit to a template-managed file; or (3) a temporary local memory only relevant to the current active work. The devcontainer environment is ephemeral, so local memory files are rarely the right choice.

## Public Repositories

- Before posting to a repository (PR or issue text, comments, commit messages, file contents), check its visibility (`gh repo view <owner>/<repo> --json visibility`). In a public repository, never name, link to, or quote a private repository. Still say when relevant work happened in one, such as testing in a private repo that depends on this one, but anonymize it ("tested in a private repo") and give only the details needed to make the point.

## Tooling

- Before hand-assembling a multi-step workflow or a polling loop, run `task --list` — it is probably already a task. Definitions live in `.config/taskfiles/`; the root `Taskfile.yaml` only includes them.
- The bans on `pnpm --prefix`, `uv --directory` and direct tool invocation apply to commands you type, not to task definitions: a task's commands run with the repo root as their working directory by default. Prefer adding or extending a task over typing the long form.
- Linting and type-checking stay with `pre-commit run <hook-id>` rather than a task or a direct tool invocation, so that what you run matches the permission allow-list and is exactly what CI runs. Each language's rule file in `.claude/rules/` lists its key hook IDs.
- `cd` into a subdirectory is auto-approved; navigating up (`cd ..`) or to an absolute path (`cd /some/path`) requires a user permission prompt. Minimize such navigation: run `pre-commit` from whichever subdirectory you're already in (it walks up to find `.pre-commit-config.yaml`).
- ❌ Never use `python3` or `python` directly. ✅ Always use `uv run python` for Python commands.
- ❌ Never use `python3`/`python` for one-off data tasks. ✅ Use `jq` for JSON parsing, standard shell builtins for string manipulation. Only reach for `uv run python` when no dedicated tool covers the need.
- ❌ Never use `uv run python -c "import ...; print(...)"` or `inspect` to introspect Python source. ✅ Read source files directly or grep for symbols — the code is on disk and can be read without running it.
- Check .devcontainer/devcontainer.json for tooling versions (Python, Node, etc.) when reasoning about version-specific stdlib or tooling behavior.
- Never use `pnpm --prefix <path>` or `uv --directory <path>` to target a different directory — these flags break the permission allow-list matcher the same way chained `cd &&` commands do. Instead, rely on the working directory already being correct (the cwd persists between Bash tool calls), or issue a plain `cd <path>` as a separate prior tool call to reposition before running the command.
- Never use backslash line continuations in shell commands — always write the full command on a single line. Backslashes break the permission allow-list matcher.
- In GitHub Codespaces, the injected `GITHUB_TOKEN` is a repo-scoped app token, so `gh`/`git` cannot reach other repos in the org. It lives in the container process environment (not any dotfile), so `unset` inside a Bash tool call does not persist. To grant broader access, ask the user to run `env -u GITHUB_TOKEN -u GH_TOKEN gh auth login --hostname github.com --git-protocol https --web --scopes workflow` in their shell (the `--web` flags are required — `gh auth login` alone needs a TTY that the Bash tool does not provide, and it refuses to store credentials while `GITHUB_TOKEN` is set; `--scopes workflow` is what lets a push change files under `.github/workflows/`, and a login made without it gains the scope with `env -u GITHUB_TOKEN -u GH_TOKEN gh auth refresh --hostname github.com --scopes workflow`). Afterwards, prefix your own `gh`/`git` calls with `env -u GITHUB_TOKEN -u GH_TOKEN` so they use the stored GitHub CLI credentials instead of the app token — `GH_TOKEN` also has to be cleared because `gh` gives it precedence over both `GITHUB_TOKEN` and stored credentials. Git gets those credentials through the `gh auth git-credential` helper that `.devcontainer/post-start-command.sh` configures, so a `git` call that fails with `could not read Username` means that helper or the stored login is missing. Where those credentials live depends on the environment (`gh` prefers the OS credential store and the config dir follows `GH_CONFIG_DIR`), but in these devcontainers they usually land in plain text at `~/.config/gh/hosts.yml`; `gh auth status` reports the active source.
- PRs are squash-merged with the PR title and description as the commit message, so a branch's commits disappear and only that message lasts. Don't cherry-pick or rewrite branch history to tidy it: plain, small commits are enough, and reviewers link to them mid-review. Put anything that should last in the PR description, written from `.github/pull_request_template.md` for a reader without your context.

### Running Tests

- Always run tests with an explicit path (e.g. uv run pytest tests/unit) — test runners discover all types (unit, integration, E2E...) by default.
- Never manually start services prior to running E2E tests. The test harness boots and tears down its own services (backend, frontend, supporting services) via session fixtures.
- When iterating on a single test, run that test in isolation first and confirm it is in the expected state (red or green) before widening to the full suite. Use the most targeted invocation available: a specific test function for Python (e.g. `uv run pytest path/to/test.py::test_name --no-cov`) or a file path and name filter for TypeScript (e.g. `pnpm test-unit path/to/test.spec.ts -t "test name" --no-coverage`). Only run the full suite once the target test behaves as expected.
- Test coverage requirements are usually at 100%, so when running a subset of tests, always disable test coverage to avoid the test run failing for insufficient coverage.

<!-- BEGIN BEADS INTEGRATION -->
## Work Tracking with bd (beads)

**IMPORTANT**: Use **bd (beads)** to break down and track your own work while implementing a ticket. Within a working session it is the only place to track that breakdown — do NOT use markdown TODOs, task lists, or other scratch tracking methods.

bd is not the team's ticket tracker. It is a local tool for a developer and an AI agent working together: `bd init --stealth` adds `.beads/` to `.git/info/exclude`, so neither the database nor its JSONL export is committed, and nothing recorded in bd is visible to reviewers, teammates, or CI. The ticket a session is implementing lives in whatever system the team owning the repository uses — GitHub Issues, Jira, Linear, or something else.

### Why bd?

- Dependency-aware: Track blockers and relationships between the pieces of work in a session
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Keeps session breakdown out of the team's ticket tracker, and out of the codebase

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task|epic|chore|decision -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:<parent-id> --json
```

**Claim and update:**

```bash
bd update <id> --status in_progress --json
bd update <id> --priority 1 --json
```

**Complete work:**

```bash
bd close <id> --reason "Completed" --json
```

**Creating human readable file:**
After every CRUD command on an issue, export it:

```bash
bd export -o [relative path to repository root]/.claude/.beads/issues-dump.jsonl
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)
- `decision` - An architectural decision (aliases: `dec`, `adr`)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready --json` shows unblocked issues
2. **Claim your task**: `bd update <id> --status in_progress --json`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id> --json`
5. **Complete**: `bd close <id> --reason "Done" --json`

After each command that changes an issue, run the export from Quick Start.


### Important Rules

- ✅ Use bd for ALL tracking of your own work within a session
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists to track session work
- ❌ Do NOT stand up a second scratch tracking system alongside bd
- ❌ Do NOT propose bd for work that needs tracking beyond the session — a bd issue is invisible to everyone else. Suggest a code comment, or a ticket in the team's own tracker, and do not assume which tracker that is

For more details, run `bd quickstart` or see <https://github.com/gastownhall/beads>.

<!-- END BEADS INTEGRATION -->

# Copier-Managed Files

Files generated from upstream copier templates are listed in `.config/.copier-managed-files.json` (if present).
The manifest has a `templates` array — one entry per template in the chain. Each entry has `src` (the template URL),
`managed_files` (files it placed), and optionally `parent_src` (the template that generated it, forming the chain).

When a file appears in multiple entries, the **last entry in the array** is the authoritative owner for backporting —
it is the most-specific template in the chain. `parent_src` lets you trace the full chain upward to the root.

When reviewing a PR that modifies a file listed in the manifest, check whether the change is generic enough to
backport to the owning template. If so, add a single summary comment (not one per file) noting which files are
template-managed and which template repo the changes should be backported to.
