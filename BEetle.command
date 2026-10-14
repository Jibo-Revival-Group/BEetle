#!/usr/bin/env bash
# Finder double-click entry; the text launchers remain unchanged.
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) || exit 1
exec /bin/bash "$repo_dir/run-gui.sh" "$@"
