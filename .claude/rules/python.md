---
paths:
  - "**/*.{py,py.jinja,py.jinja-base}"
  # In a template repository, a file rendered only on a condition has a name that ends in a Jinja tag, such as x.py{% endif %} or x.py{% endif %}.jinja. "?%" matches the "{%" that follows the extension.
  - "**/*.py?%*"
---
# Python

- In non-test code, prefer explicit `if`/`else` (or a `for` loop with `if`/`return`) over one-line forms that collapse branches: a ternary, `d.get(key, default)`, returning a boolean expression `return b > 5`/`return bool(b)`, or `any()`/`all()` over a generator in place of a loop. `coverage.py` tracks branches as line-to-line arcs, so a single-line expression hides the untaken path. Likewise, give each exception type its own `except` clause instead of catching several in one `except (A, B):` — coverage marks a combined clause covered as soon as any one of the types is caught.
- In non-test code, when filtering logic combines multiple `and`-joined guards (e.g. a null check alongside a value check), prefer a loop with explicit `if`/`continue` branches over a single-line comprehension. A compound boolean filter on one line hides individual branches from line coverage — each guard condition should be its own statement so missing test cases are surfaced.
- Python import boundaries are declared in `[tool.tach]` in `pyproject.toml` and enforced by the `tach` hook. When it flags an import, restructure the code; change the boundaries only when the user agrees they are wrong.
- Never rely on IDE diagnostics for ruff warnings — the IDE may not respect the project's ruff.toml config. Run `pre-commit run ruff -a` to get accurate results.
- Key `pre-commit` hook IDs for Python: `pyrefly`, `ruff`, `ruff-format`.
