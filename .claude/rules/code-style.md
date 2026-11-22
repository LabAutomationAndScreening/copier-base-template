---
paths:
  - "**/*.{py,py.jinja,py.jinja-base,ts,ts.jinja,vue,vue.jinja,mts,mjs,mjs.jinja}"
  # In a template repository, a file rendered only on a condition has a name that ends in a Jinja tag, such as x.py{% endif %} or x.py{% endif %}.jinja. "?%" matches the "{%" that follows the extension.
  - "**/*.{py,ts,vue,mts,mjs}?%*"
  - "**/generated/**"
---
# Code Style

- Comments should be used very rarely. Code should generally express its intent to a reader without your context.
  - A reviewer's question about what code means or why it is the way it is marks a spot where the code doesn't yet express its intent: put into the code whatever part of your answer a reader without your context would need to avoid misreading the code or undoing it.
  - If your reply to the reviewer also explains things the code can't show, such as alternatives you weighed, add those to the PR description, or to an ADR for a decision that spans modules or would be costly to reverse.
- Never write a one-line docstring — either the name is sufficient or the behavior warrants a full explanation.
- Don't name a value that is used once where a reader without your context could already tell, at the point of use, what the literal is and why it has that value — the extra variable adds a line and a hop without adding meaning. A conversion factor between units (`MILLISECONDS_PER_SECOND`, `BYTES_PER_KIB`) counts as needing its name, even used once: the literal alone doesn't say which unit it converts from, and the target's name gives only half of that.
- Prefer keyword-only parameters (unless a very clear single-argument function): use `*` in Python signatures and destructured options objects in TypeScript.
- When disabling a linting rule with an inline directive, provide a comment at the end of the line (or on the line above for tools that don't allow extra text after an inline directive) describing the reasoning for disabling the rule.
- Avoid telling the type checker what a type is rather than letting it prove it. This includes type assertions (`as SomeType` in TypeScript, `cast()` in Python) and variable annotations that override inference. Prefer approaches that let the type checker verify the type itself: `isinstance`/`instanceof` narrowing, restructuring code so the correct type flows naturally, or using discriminated unions. When there is genuinely no alternative, add a comment explaining why the workaround is necessary and why it is safe.
- In non-test code — anything coverage measures — avoid `||` (TypeScript) or `or` (Python) in `if`/`elif` conditions, and avoid `x in ['a', 'b']`-style membership tests. Coverage tools treat these as a single branch, silently masking untested paths and producing false 100% branch coverage. Use separate `if`/`elif` branches instead so each condition is independently covered. Files under a test directory are exempt because coverage never measures them, so collapsing a condition there hides nothing.
- **Never manually edit files in any `generated/` folder.** These files are produced by codegen tooling (typically Kiota) and any manual changes will be overwritten. If a generated file needs to change, update the source (e.g. the OpenAPI schema) and re-run the generator.
- Leave `import` statement ordering and unused-import removal to pre-commit — don't edit them yourself.
