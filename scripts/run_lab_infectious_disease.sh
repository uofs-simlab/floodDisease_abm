#!/usr/bin/env bash
set -euo pipefail

# Headless infectious-disease-only launcher for lab/HPC machines.

export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-1}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-1}
export VECLIB_MAXIMUM_THREADS=${VECLIB_MAXIMUM_THREADS:-1}
export NUMEXPR_NUM_THREADS=${NUMEXPR_NUM_THREADS:-1}
export PYTHONUNBUFFERED=1

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
source "$repo_root/scripts/activate_project_env.sh"

ts="$(date +"%Y%m%d_%H%M%S")"
log_dir="outputs/logs"
if ! mkdir -p "$log_dir" 2>/dev/null; then
    log_dir="${TMPDIR:-/tmp}"
    echo "[WARN] Could not create outputs/logs; falling back to $log_dir"
fi
log_file="${log_dir%/}/infectious_disease_${ts}.log"

echo "[RUN] Repo: $repo_root"
echo "[RUN] Log: $log_file"
echo "[RUN] Command: python run/infectious_disease.py $*"

set +e
python run/infectious_disease.py "$@" 2>&1 | tee "$log_file"
pipeline_status=("${PIPESTATUS[@]}")
py_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}
set -e

if [[ "$tee_status" -ne 0 ]]; then
    echo "[WARN] tee failed (exit=$tee_status). Console output was shown; log may be incomplete: $log_file" >&2
else
    echo "[OK] Log: $log_file"
fi

exit "$py_status"
