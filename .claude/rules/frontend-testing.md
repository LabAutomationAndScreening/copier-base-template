---
paths:
  - "frontend/**"
---
# Frontend Testing

- When a `data-testid` identifies one of many rendered entities, interpolate that entity's stable identifier as the dynamic value, not its display label — prefer an ID (`item.itemId`, `record.sha`) whenever the entity has one, since labels collide and change. Where the identifier *is* human-readable and no ID exists, that name is the key.
- In DOM-based unit tests, scope queries to the tightest relevant container. Only query `document` or `document.body` directly to find the top-level portal/popup element (e.g. a Reka UI dialog via `[role="dialog"][data-state="open"]`); all further queries should run on that element, not on `document.body` again. Browser automation (e.g. Playwright) fails an ambiguous single-target locator outright, so a unique `data-testid` looked up from the page is enough there.
