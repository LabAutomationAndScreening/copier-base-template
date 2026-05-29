#!/usr/bin/env bash
set -euo pipefail

# Splits pnpm-forwarded args into file paths and flags, then runs vitest with
# file paths injected before the fixed project/coverage flags so Vitest's file
# filter works correctly.
#
# Usage (from package.json scripts):
#   scripts/vitest-run.sh [fixed-vitest-flags...]
#
# When invoked via pnpm (e.g. pnpm test-unit -- file.spec.ts --no-coverage),
# pnpm appends "-- <user-args>" to the script command. This script splits at
# that "--" separator, routes args ending in ".spec.ts" before the fixed flags,
# and appends all other user flags after. Passing --no-coverage removes the
# --coverage flag from the fixed set instead of conflicting with it.

fixed=()
user=()
past_sep=false

for a in "$@"; do
  if [[ "$a" == "--" ]] && ! $past_sep; then
    past_sep=true
  elif $past_sep; then
    user+=("$a")
  else
    fixed+=("$a")
  fi
done

files=()
flags=()
no_cov=false

for a in "${user[@]}"; do
  case "$a" in
    --no-coverage) no_cov=true;;
    *.spec.ts)     files+=("$a");;
    *)             flags+=("$a");;
  esac
done

if $no_cov; then
  filtered=()
  for a in "${fixed[@]}"; do
    [[ "$a" != "--coverage" ]] && filtered+=("$a")
  done
  fixed=("${filtered[@]}")
fi

vitest run "${files[@]}" "${fixed[@]}" "${flags[@]}"
