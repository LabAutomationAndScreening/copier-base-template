---
paths:
  - "**/tests/**"
  - "**/__tests__/**"
  - "**/test_*.{py,py.jinja,py.jinja-base}"
  - "**/conftest.{py,py.jinja,py.jinja-base}"
  - "**/*.spec.ts"
  - "**/*.test.ts"
  - "**/*.spec.ts.jinja"
  - "**/*.test.ts.jinja"
---
# Testing

Write each test for a reader without your context: someone opening it because it failed or because the code it covers has to change. From the test alone, they should be able to tell what behavior it protects and which of its details that behavior depends on, so they can decide whether to fix the code, update the test, or delete it.

- Before writing a new mock, spy, stub or test-data helper, look for an existing one in the test folders' shared helper files (such as `conftest.py`, `fixtures.py`, `*-fixtures.ts`).
- A reader without your context assumes every specific value in a test was chosen because the outcome depends on it, and that goes for values in fixtures, mock return values, and fake classes as much as in the test body. Make that assumption true:
  - **Load-bearing** values (a boundary, a threshold, a regression input) stay fixed, and their reason is readable where they are defined: in a constant's name, a parametrized case's label, a helper's name, or the test title. A short comment is the fallback when no name can carry why the test uses that value.
  - **Incidental** values, where the behavior under test is the same for any valid value, are generated: faker, uuids, `random.choice` over valid values, a random enum member. When nothing generates that kind of value (a status code within a class, an instance type, a version string), write a small `_random_<thing>()` helper rather than hardcoding one example. This covers every argument of a call: when some are random and others fixed, the fixed ones read as the point of the test.
  - A random value whose range matters has load-bearing bounds, so derive them from the reason: a length that must fit within a limit is `random.randint(1, limit)`, not `random.randint(1, 2000)`.
  - Some incidental values can't be generated: a recording or snapshot pins them, or the test must use some existing thing (a route, a fixture file, a seeded record) and any one would do. Define such a value once, in a helper or constant, under a comment that says outright the choice is arbitrary in every respect a reader could wonder about (a route's path and its method; a file's name and its format). One comment can cover every value a helper defines, as when a snapshot pins a whole object. Describe whatever pins it as how the choice is carried out, not as the reason for it. Test bodies use the helper, and assertions read the value back from what the test did instead of restating it, since each repetition invites the question again.
  - Give filler neutral names (`values`, `payload`). A word from the domain under test, such as `codes` in a status-code test, makes filler look meaningful.
  - To classify a value, ask whether the behavior under test would differ with another valid value, changing anything the test wires to it along with it. No means incidental; yes means load-bearing.
- A test pins a behavior; it doesn't explain it. When the reason for a value, constraint or setting the test checks does need a comment, put it on the code that implements it, not on the test. Someone changing the code reads the code, not the test. A comment in a test only explains the test itself, such as why its setup is unusual.
- Each case of a parametrized test needs its own reason, and its label states it (in pytest, `pytest.param(499, id="highest-4xx")`), not just its value. To cover "any member of a class", use one random member labelled as such (`arbitrary-4xx`) rather than several hand-picked examples: a list of examples reads as if each one matters, and the boundary hides among them.
- Avoid loops in tests — assert each item explicitly so failures pinpoint the exact element. When verifying a condition across all items in a collection, collect the violations into a list and assert it's empty (e.g., assert [x for x in items if bad_condition(x)] == []).
- When a test's final assertion is an absence (e.g., element is `null`, list is empty, modal is closed), include a prior presence assertion confirming the expected state existed before the action that removed it. A test whose only assertion is an absence check can pass vacuously if setup silently failed.
- When asserting a mock or spy was called with specific arguments, always constrain as tightly as possible. In order of preference: (1) assert called exactly once with those args (`assert_called_once_with` in Python, `toHaveBeenCalledExactlyOnceWith` in Vitest); (2) if multiple calls are expected, assert the total call count and use a positional or last-call assertion (`toHaveBeenNthCalledWith`, `toHaveBeenLastCalledWith` / `mock.call_args_list[n] == call(...)`, `assert_called_with`, which checks only the last call); (3) plain "called with at any point" (`toHaveBeenCalledWith`, `assert_any_call`) is a last resort only when neither the call count nor the call order can reasonably be constrained.
- When asserting an exception is raised, verify the error message includes all key constructor arguments — not just one identifying field. This ensures the error message is fully populated and catches cases where arguments are swapped or missing. In Python: use the `match` parameter in `pytest.raises`. In TypeScript: use a regex or substring in `toThrow`, or catch and assert on error properties individually.
- Name tests with Given/When/Then where each clause means a specific thing: **When** names the single action under test plus the input that distinguishes this case; **Given** names only preconditions established before that action (fixtures, mocks, prior state) and is omitted when there are none; **Then** names the asserted outcome. When you change what an existing test feeds in or checks, re-derive its name from the new body; if the change adds or changes a Given or When, evaluate whether the original case still deserves its own test, with the new case in a separate one.
- A Then clause saying what did not happen ("rather than X", "instead of X", "without X-ing") needs a check of its own: keep it only where one pins X's absence and could fail while the checks on what did happen still pass. Where there is no such check, drop the clause ("rather than throwing", "without raising").
- A Given or When clause shared by every test in a group belongs on the enclosing scope (a pytest class, a `describe` block) rather than repeated in each test name. The chain from the outermost scope through the test name must read as one complete Given/When/Then, and a scope carrying a clause must state it explicitly (`TestWhenFooInvoked`, `describe("Given foo mocked to succeed")`).
- In tests that import the code under test (unit and integration), pin what the code decides, not what it states. A test protects behavior that would differ with other input or state: a branch, a computation, a fallback, wiring between parts. A fixed literal the code renders or raises verbatim (a label, an icon, a color, a fixed exception message) decides nothing, so asserting it restates the source: the test fails exactly when someone changes it on purpose and protects nothing else. Leave such literals to whatever already shows them whole (a visual regression screenshot for UI, the exception's type for a fixed message), or leave them unpinned where nothing does, rather than restating them in an assertion. When a literal is the outcome of logic, such as a default a caller gets by omitting an argument, assert the logic against the constant the code reads it from (or, when it is computed, against the relationship that computes it), not against the literal retyped. End-to-end tests see only what a user sees and cannot read the source, so whether a literal is worth checking there is a judgment call. When something outside this project (code importing it, a client of its API, a script calling its CLI) relies on a literal (an exported value, an error type, a config key, a flag), decide where that dependent would notice a change and check it there.
- Structure each test body in this order, with a blank line only where the list shows one:
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
