---
paths:
  - "**/*.{ts,ts.jinja,vue,vue.jinja,mts,mjs,mjs.jinja}"
---
# TypeScript

- For frontend tests, run commands via `pnpm` scripts from `frontend/package.json` — never invoke tools directly (not pnpm exec <tool>, npx <tool>, etc.). ✅ pnpm test-unit  ❌ pnpm vitest ... or npx vitest ...
- Key `pre-commit` hook IDs for TypeScript: `typescript-check`, `eslint`.
