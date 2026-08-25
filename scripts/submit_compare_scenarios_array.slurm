#!/bin/bash
#SBATCH --job-name=flood_batch
#SBATCH --output=outputs/logs/slurm_%A_%a.out
#SBATCH --error=outputs/logs/slurm_%A_%a.err
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --array=0-4

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

mkdir -p outputs/logs
source scripts/activate_project_env.sh

# Prevent BLAS/OpenMP oversubscription when Python already uses multiprocessing.
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-1}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-1}
export VECLIB_MAXIMUM_THREADS=${VECLIB_MAXIMUM_THREADS:-1}
export NUMEXPR_NUM_THREADS=${NUMEXPR_NUM_THREADS:-1}
export PYTHONUNBUFFERED=1

scenarios=(
  baseline
  infectious_only
  flood_only
  flood_plus_flood_disease
  flood_infectious
  full_compound
)

idx=${SLURM_ARRAY_TASK_ID:-0}
scenario=${scenarios[$idx]}
workers=${SLURM_CPUS_PER_TASK:-1}

if [[ -z "${scenario:-}" ]]; then
  echo "[ERR] Invalid SLURM_ARRAY_TASK_ID=$idx"
  exit 1
fi

ts="$(date +"%Y%m%d_%H%M%S")"
out_dir="dataCollection/scenario_runs_hpc_${ts}_${scenario}"

echo "[RUN] Scenario: $scenario"
echo "[RUN] Workers : $workers"
echo "[RUN] Out dir : $out_dir"

python run/compare_scenarios.py \
  --scenarios "$scenario" \
  --persons 300 \
  --replications 30 \
  --workers "$workers" \
  --seed-base 42 \
  --out-dir "$out_dir"

echo "[OK] Completed scenario $scenario"
