#!/usr/bin/env sh
set -eu

backend_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
venv_dir=${CANDLESCOPE_BACKEND_VENV:-"$backend_dir/.venv"}
sh "$backend_dir/setup.sh" "$@"
cd "$backend_dir"
exec "$venv_dir/bin/python" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 18080
