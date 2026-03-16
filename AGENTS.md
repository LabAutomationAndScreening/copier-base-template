## Code Style
- Comments should be used very rarely. Code should generally express its intent.
- Never write a one-line docstring — either the name is sufficient or the behavior warrants a full explanation.
- Don't sort or remove imports manually — pre-commit handles it.
- Always include type hints for pyright in Python
- Respect the pyright rule reportUnusedCallResult; assign unneeded return values to `_`
- Prefer keyword-only parameters (unless a very clear single-argument function): use `*` in Python signatures and destructured options objects in TypeScript.
- When disabling a linting rule with an inline directive, provide a comment at the end of the line (or on the line above for tools that don't allow extra text after an inline directive) describing the reasoning for disabling the rule.

## Testing
- Always run tests with an explicit path (e.g. uv run pytest tests/unit) — test runners discover all types by default.
- Test coverage requirements are usually at 100%, so when running a subset of tests, always disable test coverage to avoid the test run failing for insufficient coverage.
- Avoid magic values in comparisons in tests in all languages (like ruff rule PLR2004 specifies)
- Prefer using random values in tests rather than arbitrary ones (e.g. the faker library, uuids, random.randint) when possible.
- Avoid loops in tests — assert each item explicitly so failures pinpoint the exact element. When verifying a condition across all items in a collection, collect the violations into a list and assert it's empty (e.g., assert [x for x in items if bad_condition(x)] == []).
- Key `data-testid` selectors off unique IDs (e.g. UUIDs), not human-readable names which may collide or change.

### Python Testing
- When using `mocker.spy` on a class-level method (including inherited ones), the spy records the unbound call, so assertions need `ANY` as the first argument to match self:  `spy.assert_called_once_with(ANY, expected_arg)`
- Before writing new mock/spy helpers, check the `tests/unit/` folder for pre-built helpers in files like `fixtures.py` or `*mocks.py`
- When a test needs a fixture only for its side effects (not its return value), use `@pytest.mark.usefixtures(fixture_name.__name__)` instead of adding an unused parameter with a noqa comment
- Use `__name__` instead of string literals when referencing functions/methods (e.g., `mocker.patch.object(MyClass, MyClass.method.__name__)`, `pytest.mark.usefixtures(my_fixture.__name__)`). This enables IDE refactoring tools to catch renames.


## Tooling
- Always use `uv run python` instead of `python3` or `python` when running Python commands.
- Check .devcontainer/devcontainer.json for tooling versions (Python, Node, etc.) when reasoning about version-specific stdlib or tooling behavior.
- For frontend work, run commands via `pnpm` scripts from `frontend/package.json`. ✅ pnpm test-unit  ❌ pnpm vitest ... or npx vitest ...
- When running terminal commands, execute exactly one command per tool call. Do not chain commands with &&, ||, ;, or & unless the user explicitly asks for it. Pipes (|) are allowed for output transformation (e.g., head, tail, grep). If two sequential commands are needed, run them in separate tool calls. Chained commands break the permission allow-list matcher and cause unnecessary permission prompts
- Never use backslash line continuations in shell commands — always write the full command on a single line. Backslashes break the permission allow-list matcher.

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
