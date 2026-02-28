#!/bin/bash
set -ex

git config --global --add safe.directory /workspaces/copier-base-template
pre-commit run merge-claude-settings -a
