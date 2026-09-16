#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
MODE="${1:-cuda}"
if [[ "$MODE" != cuda && "$MODE" != cpu ]]; then echo 'Usage: bash scripts/setup_linux.sh [cuda|cpu]'; exit 2; fi
# The optional native extension needs CPython development headers (Python.h).
# Minimal images ship python3 without python3-dev; provision a project-local
# interpreter that bundles them rather than modifying the system.
if ! "$PYTHON" -c 'import pathlib,sysconfig,sys; sys.exit(0 if (pathlib.Path(sysconfig.get_paths()["include"])/"Python.h").is_file() else 1)'; then
  echo "Warning: $PYTHON has no development headers (python3-dev absent); provisioning project-locally" >&2
  PYTHON="$(bash scripts/setup_python_local.sh)"
  echo "Using project-local interpreter: $PYTHON" >&2
fi
"$PYTHON" -c 'import sys; assert (3,11)<=sys.version_info[:2]<(3,14), "Use Python 3.11-3.13; 3.12 recommended"'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements/base.txt -r requirements/dev.txt
INDEX="https://download.pytorch.org/whl/cu128"
if [[ "$MODE" == cpu ]]; then INDEX="https://download.pytorch.org/whl/cpu"; fi
.venv/bin/python -m pip install torch==2.9.1 --index-url "$INDEX"
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pip check
.venv/bin/python -m pip freeze > requirements/target-resolved.txt
if [[ "$MODE" == cuda ]]; then
 .venv/bin/python -m stsai doctor --require-cuda --output runs/doctor.json
else
 .venv/bin/python -m stsai doctor --output runs/doctor.json
fi
printf '\nActivate: source .venv/bin/activate\nThen: python -m pytest -q\n'
