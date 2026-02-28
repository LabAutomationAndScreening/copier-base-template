#!/bin/bash
set -ex

python .devcontainer/install-ci-tooling.py

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
mkdir -p "$repo_root/.claude"
chmod -R ug+rwX "$repo_root/.claude"
chgrp -R 0 "$repo_root/.claude" || true
npm --prefix "$repo_root/.claude" install json5@2.2.3 --save-exact

git config --global --add --bool push.autoSetupRemote true
git config --local core.symlinks true

sh .devcontainer/create-aws-profile.sh
