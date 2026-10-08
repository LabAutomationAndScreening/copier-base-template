#!/bin/bash
set -ex

python .devcontainer/install-ci-tooling.py

# The Biome VS Code extension finds this global install; keep the version matching the biomejs/pre-commit rev in .pre-commit-config.yaml
npm install -g @biomejs/biome@2.5.15

git config --global --add --bool push.autoSetupRemote true
git config --local core.symlinks true

sh .devcontainer/create-aws-profile.sh
