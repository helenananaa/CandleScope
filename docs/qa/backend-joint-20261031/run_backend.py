"""Run the recorded 111-module joint regression selection from an isolated venv."""
import json, os, subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[3]
files = json.loads(Path(__file__).with_name("joint-files.json").read_text())
out = root / "output/backend-joint-reproduction"
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(root / "backend"), CANDLE_DATA_DIR=str(out / "data"), CANDLESCOPE_REQUIRE_CCXT_FORK="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
raise SystemExit(subprocess.call([str(root / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "pytest_asyncio.plugin", "-p", "anyio.pytest_plugin", "-p", "pytest_timeout", "--timeout=90", "--junitxml=" + str(out / "joint.xml"), *files], cwd=root / "backend", env=env))
