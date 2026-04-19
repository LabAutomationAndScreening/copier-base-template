#!/bin/sh
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PROJECT_ROOT_DIR="${PROJECT_ROOT_DIR:-$(CDPATH= cd -- "$script_dir/../.." && pwd)}"
exec node "$script_dir/caveman-activate.js"
