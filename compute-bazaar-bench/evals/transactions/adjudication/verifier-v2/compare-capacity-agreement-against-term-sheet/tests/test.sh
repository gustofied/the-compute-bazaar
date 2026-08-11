#!/bin/bash
set -uo pipefail

tests_dir="${HARBOR_TESTS_DIR:-/tests}"
workspace="${HARBOR_WORKSPACE:-/app}"
logs_dir="${HARBOR_VERIFIER_LOG_DIR:-/logs/verifier}"

extraction_output="$(python3 "$tests_dir/extract.py" "$workspace" 2>&1)"
extraction_status=$?
printf '%s\n' "$extraction_output"

if [[ $extraction_status -eq 2 ]]; then
  HARBOR_VERIFIER_LOG_DIR="$logs_dir" python3 "$tests_dir/fail_closed.py" "$extraction_output"
  exit $?
fi
if [[ $extraction_status -ne 0 ]]; then
  exit "$extraction_status"
fi

rewardkit "$tests_dir" --workspace "$workspace" --output "$logs_dir/reward.json"
python3 "$tests_dir/__support/validate_rewardkit.py" "$logs_dir"
