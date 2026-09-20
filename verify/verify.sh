#!/bin/sh
# Acceptance entrypoint for the compose `verify` service.
# 1. End-to-end HTTP checks against the real web + api containers.
# 2. Backend solver & API test suites (with brute-force cross-checks) run
#    against the read-only mounted backend source.
set -eu

echo "=== 1/2 End-to-end HTTP acceptance checks ==="
python /app/verify_checks.py

echo ""
echo "=== 2/2 Backend solver & API test suite (brute-force cross-checked) ==="
cd /backend
PYTHONPATH=/backend:/backend/tests python -m pytest -p no:cacheprovider -q tests
