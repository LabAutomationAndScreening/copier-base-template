// Vitest 4 with inline `test.projects` config ignores positional file-path
// arguments when they appear after `--project` flags — the file filter has no
// effect and all project files run. Placing file paths BEFORE the `--project`
// flags fixes this. This script splits pnpm-forwarded args at the `--`
// separator, routes args ending in `.spec.ts` before the fixed project flags,
// and appends all other flags after them. It also handles `--no-coverage`
// overriding the `--coverage` flag that some scripts bake in.
// (No upstream Vitest issue found as of writing; file one if you find it.)
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
const sepIdx = args.indexOf("--");

const fixed = sepIdx === -1 ? args : args.slice(0, sepIdx);
const user = sepIdx === -1 ? [] : args.slice(sepIdx + 1);

const files = [];
const flags = [];
let noCoverage = false;

for (const arg of user) {
  if (arg === "--no-coverage") {
    noCoverage = true;
  } else if (arg.endsWith(".spec.ts")) {
    files.push(arg);
  } else {
    flags.push(arg);
  }
}

const fixedFiltered = noCoverage ? fixed.filter((a) => !a.startsWith("--coverage")) : fixed;

const { status } = spawnSync("vitest", ["run", ...files, ...fixedFiltered, ...flags], {
  stdio: "inherit",
});

process.exit(status ?? 1);
