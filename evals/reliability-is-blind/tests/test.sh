#!/bin/sh
set -eu

mkdir -p /logs/verifier
rm -f \
    /logs/verifier/reward.json \
    /logs/verifier/details.json \
    /logs/verifier/evidence.json

python3 /tests/verify.py
