---
paths:
  - "**/*.py"
---
# Python

- Always include type hints.
- Respect the pyrefly unused-call-result check; assign unneeded return values to `_`
- In non-test code, prefer explicit `if`/`else` (or a `for` loop with `if`/`return`) over one-line forms that collapse branches: a ternary, `d.get(key, default)`, returning a boolean expression `return b > 5`/`return bool(b)`, or `any()`/`all()` over a generator in place of a loop. `coverage.py` tracks branches as line-to-line arcs, so a single-line expression hides the untaken path.
- In non-test code, when filtering logic combines multiple `and`-joined guards (e.g. a null check alongside a value check), prefer a loop with explicit `if`/`continue` branches over a single-line comprehension. A compound boolean filter on one line hides individual branches from line coverage — each guard condition should be its own statement so missing test cases are surfaced.
