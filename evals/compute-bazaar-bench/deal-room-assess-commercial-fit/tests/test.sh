#!/bin/bash
set -u

mkdir -p /logs/verifier

if ! /usr/local/bin/python3 /tests/test_scorer.py; then
  printf '%s\n' '{"reward": 0.0, "verifier_integrity": 0}' \
    > /logs/verifier/reward.json
  exit 1
fi

/usr/local/bin/python3 /tests/score.py
