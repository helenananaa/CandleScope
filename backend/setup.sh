#!/usr/bin/env sh
set -eu

backend_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
venv_dir=${CANDLESCOPE_BACKEND_VENV:-"$backend_dir/.venv"}
bootstrap_python=${CANDLESCOPE_PYTHON:-python3}
venv_python="$venv_dir/bin/python"
requirements="$backend_dir/requirements.txt"
requirements_marker="$venv_dir/.candlescope-requirements.sha256"
ensure_plugins="$backend_dir/scripts/ensure_managed_plugins.py"
offline=0
skip_plugins=0
skip_pine=0
force_dependencies=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --offline) offline=1 ;;
        --skip-managed-plugins) skip_plugins=1 ;;
        --skip-pine-runtime) skip_pine=1 ;;
        --force-dependencies) force_dependencies=1 ;;
        *) printf 'unknown setup option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

if [ -d "$venv_dir" ] && [ ! -x "$venv_python" ]; then
    printf 'Existing backend/.venv is not a Linux virtual environment. Set CANDLESCOPE_BACKEND_VENV to another path.\n' >&2
    exit 2
fi

if [ ! -x "$venv_python" ]; then
    if ! command -v "$bootstrap_python" >/dev/null 2>&1; then
        printf 'Python command not found: %s\n' "$bootstrap_python" >&2
        exit 2
    fi
    "$bootstrap_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
        printf 'Python 3.10 or newer is required: %s\n' "$bootstrap_python" >&2
        exit 2
    }
    printf '[setup] Creating backend virtual environment at %s\n' "$venv_dir"
    "$bootstrap_python" -m venv "$venv_dir"
fi

"$venv_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
    printf 'The backend virtual environment requires Python 3.10 or newer: %s\n' "$venv_python" >&2
    exit 2
}

requirements_hash=$(
    "$venv_python" -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$requirements"
)
installed_hash=""
if [ -f "$requirements_marker" ]; then
    installed_hash=$(tr -d '[:space:]' < "$requirements_marker")
fi
if [ "$force_dependencies" -eq 1 ] || [ "$requirements_hash" != "$installed_hash" ]; then
    if [ "$offline" -eq 1 ]; then
        printf 'Offline mode requires backend dependencies from an earlier successful setup.\n' >&2
        exit 2
    fi
    printf '[setup] Installing backend dependencies\n'
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -r "$requirements"
    printf '%s\n' "$requirements_hash" > "$requirements_marker"
else
    printf '[setup] Backend dependencies are current\n'
fi

if [ "$skip_plugins" -eq 0 ]; then
    printf '[setup] Verifying managed plugins\n'
    if [ "$offline" -eq 1 ] && [ "$skip_pine" -eq 1 ]; then
        "$venv_python" "$ensure_plugins" --offline --exclude pine-compat
    elif [ "$offline" -eq 1 ]; then
        "$venv_python" "$ensure_plugins" --offline
    elif [ "$skip_pine" -eq 1 ]; then
        "$venv_python" "$ensure_plugins" --exclude pine-compat
    else
        "$venv_python" "$ensure_plugins"
    fi
else
    printf '[setup] Managed plugins were explicitly skipped\n'
fi

printf '[setup] Backend environment is ready: %s\n' "$venv_python"
