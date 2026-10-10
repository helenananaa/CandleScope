"""Regression for launching a POSIX managed sidecar through its venv link."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.plugin_runtime.registry import RuntimeProcessSpec


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv interpreter symlinks")
def test_process_spec_launch_preserves_venv_identity(tmp_path: Path) -> None:
    root = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root)], check=True)
    executable = root / "bin" / "python"
    assert executable.is_symlink()
    spec = RuntimeProcessSpec(
        runtime_id="test.venv", expected_package="test-venv", expected_version="1.0",
        executable=executable,
        arguments=("-I", "-c", "import json,sys; print(json.dumps(sys.prefix))"),
    )
    result = subprocess.run(spec.command, check=True, capture_output=True, text=True)
    assert Path(json.loads(result.stdout)) == root
