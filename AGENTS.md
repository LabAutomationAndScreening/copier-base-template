## Memory and Rules
- Before saving any memory or adding any rule, explicitly ask the user whether the concept should be: (1) added to AGENTS.md as a general rule applicable across all projects, (2) added to AGENTS.md as a rule specific to this project, or (3) stored as a temporary local memory only relevant to the current active work. The devcontainer environment is ephemeral, so local memory files are rarely the right choice.

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
- Prefer using random values in tests rather than arbitrary ones (e.g. the faker library, uuids, random.randint) when possible. For enums, pick randomly rather than hardcoding one value.
- Avoid loops in tests — assert each item explicitly so failures pinpoint the exact element. When verifying a condition across all items in a collection, collect the violations into a list and assert it's empty (e.g., assert [x for x in items if bad_condition(x)] == []).
- Key `data-testid` selectors off unique IDs (e.g. UUIDs), not human-readable names which may collide or change.

### Python Testing
- When using `mocker.spy` on a class-level method (including inherited ones), the spy records the unbound call, so assertions need `ANY` as the first argument to match self:  `spy.assert_called_once_with(ANY, expected_arg)`
- Before writing new mock/spy helpers, check the `tests/unit/` folder for pre-built helpers in files like `fixtures.py` or `*mocks.py`
- When a test needs a fixture only for its side effects (not its return value), use `@pytest.mark.usefixtures(fixture_name.__name__)` instead of adding an unused parameter with a noqa comment
- Use `__name__` instead of string literals when referencing functions/methods (e.g., `mocker.patch.object(MyClass, MyClass.method.__name__)`, `pytest.mark.usefixtures(my_fixture.__name__)`). This enables IDE refactoring tools to catch renames.
- When using the faker library, prefer the pytest fixture over instantiating instances of Faker.
- **Never hand-write VCR cassette YAML files.** Cassettes must be recorded from real HTTP interactions by running the test once with `--record-mode=once` against a live external service: `uv run pytest --record-mode=once <test path> --no-cov`. The default mode is `none` — a missing cassette will cause an error, which is expected until recorded.
- **Never hand-edit syrupy snapshot files.** Snapshots are auto-generated — to create or update them, run `uv run pytest --snapshot-update <test path> --no-cov`. A missing snapshot causes the test to fail, which is expected until you run with `--snapshot-update`. When a snapshot mismatch occurs, fix the code if the change was unintentional; run `--snapshot-update` if it was intentional.
- **Never hand-write or hand-edit pytest-reserial `.jsonl` recording files.** Recordings must be captured from real serial port traffic by running the test with `--record` while the device is connected: `uv run pytest --record <test path> --no-cov`. The default mode replays recordings — a missing recording causes an error, which is expected until recorded against a live device.


## Tooling
- Always use `uv run python` instead of `python3` or `python` when running Python commands.
- Prefer dedicated shell tools over `python3`/`python` for simple one-off tasks: use `jq` for JSON parsing, standard shell builtins for string manipulation, etc. Only reach for `python3` when no simpler tool covers the need.
- Check .devcontainer/devcontainer.json for tooling versions (Python, Node, etc.) when reasoning about version-specific stdlib or tooling behavior.
- For frontend tests, run commands via `pnpm` scripts from `frontend/package.json` — never invoke tools directly (not pnpm exec <tool>, npx <tool>, etc.). ✅ pnpm test-unit  ❌ pnpm vitest ... or npx vitest ...
- For linting and type-checking, prefer `pre-commit run <hook-id>` over invoking tools directly — this matches the permission allow-list and mirrors what CI runs. Key hook IDs: `typescript-check`, `eslint`, `pyright`, `ruff`, `ruff-format`.
- When running terminal commands, execute exactly one command per tool call. Do not chain commands with &&, ||, ;, or & — this prohibition has no exceptions, even for `cd && ...` patterns. Use absolute paths instead of `cd` to avoid needing to chain. Pipes (|) are allowed for output transformation (e.g., head, tail, grep). If two sequential commands are needed, run them in separate tool calls. Chained commands break the permission allow-list matcher and cause unnecessary permission prompts
- Never use backslash line continuations in shell commands — always write the full command on a single line. Backslashes break the permission allow-list matcher.
- **Never manually edit files in any `generated/` folder.** These files are produced by codegen tooling (typically Kiota) and any manual changes will be overwritten. If a generated file needs to change, update the source (e.g. the OpenAPI schema) and re-run the generator.

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
