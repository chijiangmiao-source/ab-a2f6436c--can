#!/bin/sh
# Acceptance entrypoint: solver unit tests first, then end-to-end checks.
set -e

echo "########## solver unit tests ##########"
python -m pytest -q test_solver.py

echo ""
echo "########## end-to-end acceptance ##########"
exec python /acceptance/verify.py
