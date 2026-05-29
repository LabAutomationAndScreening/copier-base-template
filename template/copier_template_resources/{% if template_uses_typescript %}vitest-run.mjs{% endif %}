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

const fixedFiltered = noCoverage ? fixed.filter((a) => a !== "--coverage") : fixed;

const { status } = spawnSync("vitest", ["run", ...files, ...fixedFiltered, ...flags], {
  stdio: "inherit",
});

process.exit(status ?? 1);
