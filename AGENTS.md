## Code Style
- Comments should be used very rarely. Code should generally express its intent.
- Never write a one-line docstring — either the name is sufficient or the behavior warrants a full explanation.
- Don't sort or remove imports manually — pre-commit handles it.
- Always include type hints for pyright in Python
- Respect the pyright rule reportUnusedCallResult; assign unneeded return values to `_`
- Prefer keyword-only parameters: use `*` in Python signatures and destructured options objects in TypeScript.

## Testing
- Always run tests with an explicit path (e.g. uv run pytest tests/unit) — test runners discover all types by default.
- Test coverage requirements are usually at 100%, so when running a subset of tests, always disable test coverage to avoid the test run failing for insufficient coverage.
- Avoid magic values in comparisons in tests in all languages (like ruff rule PLR2004 specifies)
- Prefer using random values in tests rather than arbitrary ones (e.g. the faker library, uuids, random.randint) when possible.

## Tooling
- Always use `uv run python` instead of `python3` or `python` when running Python commands.
- Check .devcontainer/devcontainer.json for tooling versions (Python, Node, etc.) when reasoning about version-specific stdlib or tooling behavior.
<!-- Allows better automated utilization of command allow/deny list -->
- When running terminal commands, execute exactly one command per tool call. Do not chain commands with &&, ||, ;, or & unless the user explicitly asks for it. Pipes (|) are allowed for output transformation (e.g., head, tail, grep). If two sequential commands are needed, run them in separate tool calls.

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
bd export -o .claude/.beads/issues-dump.jsonl
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

<!-- END BEADS INTEGRATION -->
