# Project Structure

This project is a Copier template used to generate other copier templates. It is the "grandparent" of actual instantiated application/library repositories.

# Code Guidelines

## Code Style

- Comments should be used very rarely. Code should generally express its intent.
- Don't name a value that is used once where the literal is already self-explanatory at the point of use — the extra variable adds a line and a hop without adding meaning.
- Prefer keyword-only parameters (unless a very clear single-argument function). See the language rules for the idiom.
- When disabling a linting rule with an inline directive, provide a comment at the end of the line (or on the line above for tools that don't allow extra text after an inline directive) describing the reasoning for disabling the rule.
- Avoid telling the type checker what a type is rather than letting it prove it — prefer type narrowing, restructuring, or discriminated unions over assertions and inference-overriding annotations. See the language rules for specifics.
- In non-test code — anything coverage measures — avoid collapsing multiple conditions into a single branch (compound boolean `if` conditions, membership tests); coverage tools treat them as one branch and silently mask untested paths. See the language rules for specifics.

Language- and path-specific guidance (Python, TypeScript, testing, frontend) lives in `.claude/rules/*.md` and loads on demand when Claude reads matching files. Other tools that read only AGENTS.md should also consult `.claude/rules/`.

# Agent Implementations & Configurations

## Memory and Rules

- Before saving any memory or adding any rule, explicitly ask the user whether the concept should be: (1) added to AGENTS.md as a general rule applicable across all projects, (2) added to AGENTS.md as a rule specific to this project, or (3) stored as a temporary local memory only relevant to the current active work. The devcontainer environment is ephemeral, so local memory files are rarely the right choice.

## Tooling

- ❌ Never chain commands (`&&`, `||`, `;`, `&`) — breaks permission allow-list matcher. ✅ One command per tool call. `cd` as separate prior call. Pipes (`|`) OK.
- Before hand-assembling a multi-step workflow, run `task --list` — it is probably already a task. Definitions live in `.config/taskfiles/`; the root `Taskfile.yaml` only includes them.
- The bans on `pnpm --prefix`, `uv --directory` and direct tool invocation apply to commands you type, not to task definitions: a task's commands run with the repo root as their working directory by default. Prefer adding or extending a task over typing the long form.
- Linting and type-checking stay with `pre-commit run <hook-id>` rather than a task, so that what you run is exactly what CI runs.
- `cd` into a subdirectory is auto-approved; navigating up (`cd ..`) or to an absolute path (`cd /some/path`) requires a user permission prompt. Minimize such navigation: run `pre-commit` from whichever subdirectory you're already in (it walks up to find `.pre-commit-config.yaml`).
- ❌ Never use `python3` or `python` directly. ✅ Always use `uv run python` for Python commands.
- ❌ Never use `python3`/`python` for one-off data tasks. ✅ Use `jq` for JSON parsing, standard shell builtins for string manipulation. Only reach for `uv run python` when no dedicated tool covers the need.
- ❌ Never use `uv run python -c "import ...; print(...)"` or `inspect` to introspect Python source. ✅ Read source files directly or grep for symbols — the code is on disk and can be read without running it.
- Check .devcontainer/devcontainer.json for tooling versions (Python, Node, etc.) when reasoning about version-specific stdlib or tooling behavior.
- For frontend tests, run commands via `pnpm` scripts from `frontend/package.json` — never invoke tools directly (not pnpm exec <tool>, npx <tool>, etc.). ✅ pnpm test-unit  ❌ pnpm vitest ... or npx vitest ...
- ❌ Never invoke a linter, formatter, or type-checker binary directly — not `ruff`, `ruff-format`, `pyrefly`, `biome`, `eslint`, `tsc`/`vue-tsc`, `prettier`, and never via `uv run <tool>`, `npx <tool>`, or `pnpm exec <tool>`. ✅ Always run its pre-commit gate: `pre-commit run <hook-id> -a`. This mirrors CI exactly and respects the permission allow-list; a directly-run binary may use a different config or version (e.g. an IDE ignoring `ruff.toml`) and silently diverge from CI.
  - **When:** after editing any file, and again before every commit, run the relevant `pre-commit run <hook-id> -a`. Do not defer linting/type-checking to "later" — gate each change as you make it.
  - **Finding the id:** discover hook ids from `.pre-commit-config.yaml` (e.g. `ruff`, `ruff-format`, `pyrefly`, `biome-check`, `prettier`). If you don't know the id, run `pre-commit run --all-files` — never fall back to calling the tool directly because you couldn't find the id.
- Never rely on IDE diagnostics for ruff warnings — the IDE may not respect the project's ruff.toml config. Run `pre-commit run ruff -a` to get accurate results.
- Never use `pnpm --prefix <path>` or `uv --directory <path>` to target a different directory — these flags break the permission allow-list matcher the same way chained `cd &&` commands do. Instead, rely on the working directory already being correct (the cwd persists between Bash tool calls), or issue a plain `cd <path>` as a separate prior tool call to reposition before running the command.
- Never use backslash line continuations in shell commands — always write the full command on a single line. Backslashes break the permission allow-list matcher.
- **Never manually edit files in any `generated/` folder.** These files are produced by codegen tooling (typically Kiota) and any manual changes will be overwritten. If a generated file needs to change, update the source (e.g. the OpenAPI schema) and re-run the generator.
- Leave `import` statement ordering and unused-import removal to pre-commit — don't edit them yourself.
- In GitHub Codespaces, the injected `GITHUB_TOKEN` is a repo-scoped app token, so `gh`/`git` cannot reach other repos in the org. It lives in the container process environment (not any dotfile), so `unset` inside a Bash tool call does not persist. To grant broader access, ask the user to run `env -u GITHUB_TOKEN -u GH_TOKEN gh auth login --hostname github.com --git-protocol https --web` in their shell (the `--web` flags are required — `gh auth login` alone needs a TTY that the Bash tool does not provide, and it refuses to store credentials while `GITHUB_TOKEN` is set). Afterwards, prefix your own `gh`/`git` calls with `env -u GITHUB_TOKEN -u GH_TOKEN` so they use the stored GitHub CLI credentials instead of the app token — `GH_TOKEN` also has to be cleared because `gh` gives it precedence over both `GITHUB_TOKEN` and stored credentials. Where those credentials live depends on the environment (`gh` prefers the OS credential store and the config dir follows `GH_CONFIG_DIR`), but in these devcontainers they usually land in plain text at `~/.config/gh/hosts.yml`; `gh auth status` reports the active source.

<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Auto-syncs to JSONL for version control
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update bd-42 --status in_progress --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
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

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task**: `bd update <id> --status in_progress`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`


### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

# Copier-Managed Files

Files generated from upstream copier templates are listed in `.config/.copier-managed-files.json` (if present).
The manifest has a `templates` array — one entry per template in the chain. Each entry has `src` (the template URL),
`managed_files` (files it placed), and optionally `parent_src` (the template that generated it, forming the chain).

When a file appears in multiple entries, the **last entry in the array** is the authoritative owner for backporting —
it is the most-specific template in the chain. `parent_src` lets you trace the full chain upward to the root.

When reviewing a PR that modifies a file listed in the manifest, check whether the change is generic enough to
backport to the owning template. If so, add a single summary comment (not one per file) noting which files are
template-managed and which template repo the changes should be backported to.

<!-- END BEADS INTEGRATION -->
