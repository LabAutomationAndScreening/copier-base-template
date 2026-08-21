---
paths:
  - "**/test_*.py"
  - "**/tests/**"
  - "**/*.spec.ts"
  - "**/*.test.ts"
---
# Testing

- Always run tests with an explicit path (e.g. uv run pytest tests/unit) — test runners discover all types (unit, integration, E2E...) by default.
- Never manually start services prior to running E2E tests. The test harness boots and tears down its own services (backend, frontend, supporting services) via session fixtures.
- When iterating on a single test, run that test in isolation first and confirm it is in the expected state (red or green) before widening to the full suite. Use the most targeted invocation available: a specific test function for Python (e.g. `uv run pytest path/to/test.py::test_name --no-cov`) or a file path and name filter for TypeScript (e.g. `pnpm test-unit path/to/test.spec.ts -t "test name" --no-coverage`). Only run the full suite once the target test behaves as expected.
- Test coverage requirements are usually at 100%, so when running a subset of tests, always disable test coverage to avoid the test run failing for insufficient coverage.
- Avoid magic values in comparisons in tests in all languages (like ruff rule PLR2004 specifies). Note: `1` and `0` are not magic numbers (according to PLR2004)
- Prefer using random values in tests rather than arbitrary ones (e.g. the faker library, uuids, random.randint) when possible. For enums, pick randomly rather than hardcoding one value.
- Avoid loops in tests — assert each item explicitly so failures pinpoint the exact element. When verifying a condition across all items in a collection, collect the violations into a list and assert it's empty (e.g., assert [x for x in items if bad_condition(x)] == []).
- When a test's final assertion is an absence (e.g., element is `null`, list is empty, modal is closed), include a prior presence assertion confirming the expected state existed before the action that removed it. A test whose only assertion is an absence check can pass vacuously if setup silently failed.
- When asserting a mock or spy was called with specific arguments, always constrain as tightly as possible. In order of preference: (1) assert called exactly once with those args (`assert_called_once_with` in Python, `toHaveBeenCalledExactlyOnceWith` in Vitest/Jest); (2) if multiple calls are expected, assert the total call count and use a positional or last-call assertion (`nthCalledWith`, `lastCalledWith` / `assert_has_calls` with `call_args_list[n]`); (3) plain "called with at any point" (`toHaveBeenCalledWith`, `assert_called_with`) is a last resort only when neither the call count nor the call order can reasonably be constrained.
- When asserting an exception is raised, verify the error message includes all key constructor arguments — not just one identifying field. This ensures the error message is fully populated and catches cases where arguments are swapped or missing. In Python: use the `match` parameter in `pytest.raises`. In TypeScript: use a regex or substring in `toThrow`, or catch and assert on error properties individually.
- Name tests with Given/When/Then where each clause means a specific thing: **When** names the single action under test plus the input that distinguishes this case; **Given** names only preconditions established before that action (fixtures, mocks, prior state) and is omitted when there are none; **Then** names the asserted outcome.
- A Given or When clause shared by every test in a group belongs on the enclosing scope (a pytest class, a `describe` block) rather than repeated in each test name. The chain from the outermost scope through the test name must read as one complete Given/When/Then, and a scope carrying a clause must state it explicitly (`TestWhenFooInvoked`, `describe("Given foo mocked to succeed")`).
- When an exception has a fixed message with no variable data, prefer a specific exception subclass over `match` — the subclass type is the full assertion, and matching a hardcoded string duplicates the exception class without adding test value. In this case, suppress PT011 with an inline `# noqa: PT011` comment explaining why.
- Structure each test body in this order, with a single blank line separating each section:
  1. **Constants** — random/faker values and test data objects
  2. **Mocks/spies** — all spy and patch setups
  3. **Arrange** — setup calls that establish the precondition (mounting, pre-act interactions, etc.)
  4. *(blank line)*
  5. **Act** — the action under test
  6. *(blank line)*
  7. **State capture** — variables extracted from the system under test purely for use in assertions (DOM queries, return values, captured state)
  8. *(blank line)*
  9. **Assertions**

  For tests with multiple interaction steps (e.g. E2E or complex flows), repeat the Act → State capture → Assertions cycle, with a blank line between each cycle.

  Keep blank lines to a minimum: only where they separate meaningful sections to enhance code readability.
