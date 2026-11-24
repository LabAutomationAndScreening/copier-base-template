---
paths:
  - "**/*.{vue,vue.jinja}"
  - "**/tests/**/*.{ts,ts.jinja}"
  # In a template repository, a file rendered only on a condition has a name that ends in a Jinja tag, such as x.spec.ts{% endif %} or x.spec.ts{% endif %}.jinja. "?%" matches the "{%" that follows the extension.
  - "**/*.vue?%*"
  - "**/tests/**/*.ts?%*"
  - "**/__tests__/**/*.ts"
  - "**/*.spec.ts"
  - "**/*.test.ts"
  - "**/*.spec.ts.jinja"
  - "**/*.test.ts.jinja"
---
# Frontend Testing

- Fixed copy and presentation in a component (labels, icons, colors, variants, spacing) belong to visual regression tests, not unit assertions: a screenshot pins them together and updates as one reviewed baseline. Unit tests cover what the component computes or wires: conditional rendering, text derived from props or state, and interactions such as a toggle revealing content. Accessible names and roles are not presentation: a screenshot can't show them, and assistive technology relies on them, so decide where a change to one would be noticed and check it there.
- When a `data-testid` identifies one of many rendered entities, interpolate that entity's stable identifier as the dynamic value, not its display label — prefer an ID (`item.itemId`, `record.sha`) whenever the entity has one, since labels collide and change. Where the identifier *is* human-readable and no ID exists, that name is the key.
- In DOM-based unit tests, scope queries to the tightest relevant container. Only query `document` or `document.body` directly to find the top-level portal/popup element (e.g. a Reka UI dialog via `[role="dialog"][data-state="open"]`); all further queries should run on that element, not on `document.body` again. Browser automation (e.g. Playwright) fails an ambiguous single-target locator outright, so a unique `data-testid` looked up from the page is enough there.
