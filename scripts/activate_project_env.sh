#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${FLOOD_PROJECT_ACTIVATE:-}" ]]; then
	activate_candidates=("${FLOOD_PROJECT_ACTIVATE}")
else
	activate_candidates=(
		".venv/bin/activate"
		".venv/Scripts/activate"
		"flood-env/bin/activate"
		"flood-env/Scripts/activate"
		"venv/bin/activate"
		"venv/Scripts/activate"
		"env/bin/activate"
		"env/Scripts/activate"
	)
fi

activate_path=""
for candidate in "${activate_candidates[@]}"; do
	if [[ -f "$repo_root/$candidate" ]]; then
		activate_path="$repo_root/$candidate"
		break
	fi
done

if [[ -z "$activate_path" ]]; then
	echo "[ENV] No project virtual environment found under $repo_root" >&2
	echo "[ENV] Checked: ${activate_candidates[*]}" >&2
	return 1 2>/dev/null || exit 1
fi

# shellcheck source=/dev/null
source "$activate_path"
export FLOOD_PROJECT_ACTIVATE_PATH="$activate_path"

python_bin="$(command -v python)"
echo "[ENV] Activated $activate_path" >&2
echo "[ENV] Python: $python_bin" >&2
