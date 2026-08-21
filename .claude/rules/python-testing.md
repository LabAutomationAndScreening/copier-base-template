---
paths:
  - "**/test_*.py"
  - "**/tests/**/*.py"
---
# Python Testing

- Do not apply the keyword-only parameter rule (`*`) to test functions or fixtures — pytest injects its parameters, so `*` has no effect.
- When using `mocker.spy` on a class-level method (including inherited ones), the spy records the unbound call, so assertions need `ANY` as the first argument to match self: `spy.assert_called_once_with(ANY, expected_arg)`
- Before writing new mock/spy helpers, check the `tests/unit/` folder for pre-built helpers in files like `fixtures.py` or `*mocks.py`
- When a test needs a fixture only for its side effects (not its return value), use `@pytest.mark.usefixtures(fixture_name.__name__)` instead of adding an unused parameter with a noqa comment
- Use `__name__` instead of string literals when referencing functions/methods (e.g., `mocker.patch.object(MyClass, MyClass.method.__name__)`, `pytest.mark.usefixtures(my_fixture.__name__)`). This enables IDE refactoring tools to catch renames.
- When using the faker library, prefer the pytest fixture (provided by the faker library) over instantiating instances of Faker.
- **Choosing between cassettes and mocks:** At the layer that directly wraps an external API or service, strongly prefer VCR cassette-recorded interactions (via pytest-recording/vcrpy) — they capture real HTTP traffic and verify the wire format, catching integration issues that mocks would miss. At layers above that (e.g. business logic, route handlers), mock the wrapper layer instead (e.g. `mocker.patch.object(ThresholdsRepository, ...)`) — there is no value in re-testing the HTTP interaction from higher up.
- **Never hand-write VCR cassette YAML files.** Cassettes must be recorded from real HTTP interactions by running the test once with `--record-mode=once` against a live external service: `uv run pytest --record-mode=once <test path> --no-cov`. The default mode is `none` — a missing cassette will cause an error, which is expected until recorded.
- **Never hand-edit syrupy snapshot files.** Snapshots are auto-generated — to create or update them, run `uv run pytest --snapshot-update <test path> --no-cov`. A missing snapshot causes the test to fail, which is expected until you run with `--snapshot-update`. When a snapshot mismatch occurs, fix the code if the change was unintentional; run `--snapshot-update` if it was intentional.
