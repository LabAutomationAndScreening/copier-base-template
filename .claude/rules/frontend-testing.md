---
paths:
  - "frontend/**"
  - "**/*.spec.ts"
  - "**/*.test.ts"
---
# Frontend Testing

Frontend (TypeScript) testing mechanics. General principles live in `testing.md`.

- Targeted single-test invocation: a file path plus name filter, e.g. `pnpm test-unit path/to/test.spec.ts -t "test name" --no-coverage`. When running a subset, disable coverage with `--no-coverage` so the run doesn't fail on insufficient coverage.
- Tight mock/spy argument matchers, in order of preference: (1) `toHaveBeenCalledExactlyOnceWith`; (2) multiple calls — `nthCalledWith` / `lastCalledWith`; (3) last resort `toHaveBeenCalledWith`.
- Asserting a thrown error's message: use a regex or substring in `toThrow`, or catch and assert on error properties individually.
- When a `data-testid` identifies one of many rendered entities, interpolate that entity's stable identifier as the dynamic value, not its display label — prefer an ID (`item.itemId`, `record.sha`) whenever the entity has one, since labels collide and change. Where the identifier *is* human-readable and no ID exists, that name is the key.
- In DOM-based unit tests, scope queries to the tightest relevant container. Only query `document` or `document.body` directly to find the top-level portal/popup element (e.g. a Reka UI dialog via `[role="dialog"][data-state="open"]`); all further queries should run on that element, not on `document.body` again. Browser automation (e.g. Playwright) fails an ambiguous single-target locator outright, so a unique `data-testid` looked up from the page is enough there.
