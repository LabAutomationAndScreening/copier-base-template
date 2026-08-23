---
paths:
  - "**/*.spec.ts"
  - "**/*.test.ts"
---
# Frontend Testing

Frontend (TypeScript) testing mechanics. General principles live in `testing.md`.

## Unit Testing

- Run tests with an explicit path, e.g. `pnpm test-unit tests/unit`.
- Targeted single-test invocation: a file path plus name filter, e.g. `pnpm test-unit path/to/test.spec.ts -t "test name" --no-coverage`. When running a subset, disable coverage with `--no-coverage` so the run doesn't fail on insufficient coverage.
- Tight mock/spy argument matchers, in order of preference: (1) `toHaveBeenCalledExactlyOnceWith`; (2) multiple calls — `nthCalledWith` / `lastCalledWith`; (3) last resort `toHaveBeenCalledWith`.
- Asserting a thrown error's message: use a regex or substring in `toThrow`, or catch and assert on error properties individually.
- When a `data-testid` identifies one of many rendered entities, interpolate that entity's stable identifier as the dynamic value, not its display label — prefer an ID (`item.itemId`, `record.sha`) whenever the entity has one, since labels collide and change. Where the identifier *is* human-readable and no ID exists, that name is the key.
- In DOM-based unit tests, scope queries to the tightest relevant container. Only query `document` or `document.body` directly to find the top-level portal/popup element (e.g. a Reka UI dialog via `[role="dialog"][data-state="open"]`); all further queries should run on that element, not on `document.body` again. Browser automation (e.g. Playwright) fails an ambiguous single-target locator outright, so a unique `data-testid` looked up from the page is enough there.

## End-to-End vs Visual Regression (Playwright)

E2E and VRT specs commonly live side by side (e.g. under `tests/e2e/`), split by filename (`*.spec.ts` for behavioral, `*.vrt.spec.ts` for screenshot) and by fixture. They cover different things and must not overlap — an assertion belongs in exactly one of the two.

### End-to-End (behavioral)

- Assert what a screenshot cannot: DOM presence/absence, text content, counts, ordering, and URL/query state (`toHaveText`, `toContainText`, `toBeVisible`, `toHaveCount(0)`, `toHaveURL`).
- Do not take screenshots in an e2e spec — behavior is the subject, not appearance.

### Visual Regression (VRT)

- A VRT navigates, settles the page to a stable frame, then takes one screenshot. The screenshot **is** the assertion.
- **Do not assert CSS, colors, computed styles, text, counts, or element presence in a VRT.** The screenshot comparison already covers everything visible; re-asserting visual content is redundant and couples the test to details the baseline already guards.
- The only `expect`s a VRT should contain are stability gates — wait for the key elements to be visible so the frame is settled before capture. When a VRT interacts to reach a state, assert just enough to confirm the state was reached (e.g. `toHaveCount(2)`), then screenshot; do not re-assert the resulting visuals.
- Prefer an element-scoped screenshot for a self-contained widget so its baseline is insensitive to unrelated layout changes; use a page/pane-level screenshot for layout itself.
- Make captures deterministic: freeze time (`page.clock.setFixedTime(...)`), use fixed test data, and wait on a readiness gate so nothing is captured mid-load. Mask dynamic content that cannot be frozen (e.g. time-axis tick labels) via the `mask` option.
- Set stable screenshot options globally in `playwright.config.ts` (`animations: "disabled"`, `caret: "hide"`, a small `maxDiffPixelRatio`); override `viewport` per file when content doesn't fit.
- VRT baselines are platform-dependent — generate them on one platform (e.g. Linux/CI) and skip VRTs elsewhere (e.g. a Windows-skip fixture).
- **Never hand-edit screenshot baseline files.** Regenerate them by running the e2e suite with `--update-snapshots` (e.g. `pnpm test-e2e:update-snapshots`); a missing or changed baseline fails the test until regenerated. When a diff appears, fix the code if the change was unintended, or update the baseline if it was intended.
