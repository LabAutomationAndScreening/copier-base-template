#!/bin/bash
set -ex
# TODO: update the devcontainer hash script to exclude this file, since rebuilding the devcontainer wouldn't rely on this
git config --global --add safe.directory /workspaces/copier-base-template
pre-commit run merge-claude-settings -a

if ! bd ready --json; then
	echo "It's likely the Dolt server has not yet been initialized to support beads, running that now" # TODO: figure out a better way to match this specific scenario than just a non-zero exit code...but beads still seems like in high flux right now so not sure what to tie it to
    # the 'stealth' flag is just the only way I could figure out how to stop it from modifying AGENTS.md...if there's another way to avoid that, then fine.  Even without the stealth flag though, files inside the .claude/beads directory get modified, so restoring them at the end to what was set in git...these shouldn't really need to change regularly
    rm -rf .claude/.beads && bd init --skip-hooks --prefix= --stealth </dev/null && git -c core.hooksPath=/dev/null restore --source=HEAD --staged --worktree .claude/.beads
fi
