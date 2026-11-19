---
paths:
  - "**/*.{py,py.jinja,py.jinja-base}"
---
# Python

- Always include type hints.
- In non-test code, prefer explicit `if`/`else` (or a `for` loop with `if`/`return`) over one-line forms that collapse branches: a ternary, `d.get(key, default)`, returning a boolean expression `return b > 5`/`return bool(b)`, or `any()`/`all()` over a generator in place of a loop. `coverage.py` tracks branches as line-to-line arcs, so a single-line expression hides the untaken path. Likewise, give each exception type its own `except` clause instead of catching several in one `except (A, B):` — coverage marks a combined clause covered as soon as any one of the types is caught.
- In non-test code, when filtering logic combines multiple `and`-joined guards (e.g. a null check alongside a value check), prefer a loop with explicit `if`/`continue` branches over a single-line comprehension. A compound boolean filter on one line hides individual branches from line coverage — each guard condition should be its own statement so missing test cases are surfaced.
