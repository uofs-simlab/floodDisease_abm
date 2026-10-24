#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if python3 -c "import ensurepip" >/dev/null 2>&1; then
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
else
    python3 -m venv --without-pip .venv
    python3 -m pip --python "$repo_root/.venv/bin/python" install --upgrade pip
    source .venv/bin/activate
fi

python -m pip install -r requirements.txt

echo "[OK] Environment ready. Runner scripts will auto-activate it from now on."
