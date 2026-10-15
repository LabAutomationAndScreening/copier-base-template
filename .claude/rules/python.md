---
paths:
  - "**/*.py"
---
# Python

## Code Style

- Always include type hints.
- Respect the pyrefly unused-call-result check; assign unneeded return values to `_`
- Never write a one-line docstring — either the name is sufficient or the behavior warrants a full explanation.
- Prefer keyword-only parameters — use `*` in signatures (unless a very clear single-argument function).
- Avoid telling the type checker what a type is rather than letting it prove it: avoid `cast()` and variable annotations that override inference. Prefer `isinstance` narrowing or restructuring so the correct type flows naturally. When there is genuinely no alternative, add a comment explaining why the workaround is necessary and why it is safe.
- In non-test code, prefer explicit `if`/`else` (or a `for` loop with `if`/`return`) over one-line forms that collapse branches: a ternary, `d.get(key, default)`, returning a boolean expression `return b > 5`/`return bool(b)`, or `any()`/`all()` over a generator in place of a loop. `coverage.py` tracks branches as line-to-line arcs, so a single-line expression hides the untaken path.
- In non-test code, when filtering logic combines multiple `and`-joined guards (e.g. a null check alongside a value check), prefer a loop with explicit `if`/`continue` branches over a single-line comprehension. A compound boolean filter on one line hides individual branches from line coverage — each guard condition should be its own statement so missing test cases are surfaced.
