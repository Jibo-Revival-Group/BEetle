#!/usr/bin/env bash
# Desktop wrapper: keep updates and backups relative to the toolkit, not the file manager.
set -uo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd) || exit 1
cd -- "$repo_dir" || exit 1
/bin/bash "$repo_dir/run.sh" --gui "$@"
status=$?
if (( status != 0 )) && [[ -t 0 ]]; then
  printf '\nToolkit exited with code %s. Press Enter to close this terminal.\n' "$status" >&2
  read -r _ || true
fi
exit "$status"
