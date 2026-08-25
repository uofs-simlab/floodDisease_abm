#!/usr/bin/env bash
set -euo pipefail

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
mkdir -p outputs/logs
log_file="outputs/logs/flood_infectious_${ts}.log"
echo "[RUN] Repo: $repo_root"
echo "[RUN] Log: $log_file"
echo "[RUN] Command: python run/flood_infectious.py $*"

set +e
python run/flood_infectious.py "$@" 2>&1 | tee "$log_file"
pipeline_status=("${PIPESTATUS[@]}")
py_status=${pipeline_status[0]}
set -e
exit "$py_status"
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
source scripts/activate_project_env.sh

mkdir -p outputs/logs
log_dir="outputs/logs"
ts="$(date +"%Y%m%d_%H%M%S")"
log_file="${log_dir%/}/flood_infectious_${ts}.log"
echo "[RUN] Command: python run/flood_infectious.py $*" | tee "$log_file"
python run/flood_infectious.py "$@" 2>&1 | tee -a "$log_file"
