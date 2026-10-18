from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.backtest.external_provider.sample import descriptor


def test_host_reads_only_data_identity_matching_the_isolated_external_launcher(tmp_path):
    sample = descriptor()
    process = subprocess.run(sample["argv"] + ["--manifest"], cwd=tmp_path,
                             env=dict(os.environ, PYTHONPATH="/not-a-host-package-path"),
                             capture_output=True, text=True, timeout=3, check=True)
    assert json.loads(process.stdout) == sample["manifest"]
    assert not process.stderr


def test_example_source_launches_after_relocation_without_host_or_site_packages(tmp_path):
    source = Path(__file__).parents[2] / "packages" / "candlescope-external-provider"
    relocated = tmp_path / "External Model Relocated"
    shutil.copytree(source, relocated, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    process = subprocess.run([sys.executable, "-I", "-S", "-B", str(relocated / "run_example.py"), "--manifest"],
                             cwd=tmp_path, capture_output=True, text=True, timeout=3, check=True)
    assert json.loads(process.stdout) == descriptor()["manifest"]
    assert not process.stderr
