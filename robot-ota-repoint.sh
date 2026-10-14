#!/usr/bin/env bash
# Compatibility entry point for BEetle's shared 5x1 workflow.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "${JIBO_PYTHON:-python3}" "$repo_dir/jibo_dfu.py" setup-5x1 "$@"
