---
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.vue"
---
# TypeScript

## Code Style

- Prefer destructured options objects over positional parameters (unless a very clear single-argument function).
- Avoid telling the type checker what a type is rather than letting it prove it: avoid `as SomeType` assertions and variable annotations that override inference. Prefer `instanceof` narrowing, discriminated unions, or restructuring so the correct type flows naturally. When there is genuinely no alternative, add a comment explaining why the workaround is necessary and why it is safe.
- In non-test code — anything coverage measures — avoid `||` in `if`/`else if` conditions and `[...].includes(x)`-style membership tests. Coverage tools treat these as a single branch, silently masking untested paths and producing false 100% branch coverage. Use separate `if`/`else if` branches so each condition is independently covered. Files under a test directory are exempt because coverage never measures them.
