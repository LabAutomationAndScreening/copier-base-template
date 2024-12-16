#!/usr/bin/env bash
set -ex

SCRIPT_DIR="$(dirname "$0")"
PROJECT_ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# Ensure that the lock file is in a good state
uv lock --check --directory $PROJECT_ROOT_DIR

uv sync --frozen --directory $PROJECT_ROOT_DIR
