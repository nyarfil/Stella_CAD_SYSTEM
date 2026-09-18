#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
if [ -x .venv/bin/python ]; then exec .venv/bin/python scripts/setup_req2cad.py "$@"; else exec python3 scripts/setup_req2cad.py "$@"; fi
