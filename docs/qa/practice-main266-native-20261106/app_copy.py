"""Copy the physical app before any candidate-specific mutation."""
from pathlib import Path
import subprocess


def clone_app(source: Path, destination: Path) -> Path:
    physical_source = source.resolve(strict=True)
    if not physical_source.is_dir():
        raise NotADirectoryError(str(source))
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(str(destination))
    physical_destination = destination.resolve()
    if physical_source == physical_destination or physical_source in physical_destination.parents:
        raise ValueError("Candidate must be outside the source app")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/bin/cp", "-cR", str(physical_source), str(destination)], check=True)
    if destination.is_symlink() or not destination.is_dir():
        raise RuntimeError("Candidate copy must be a physical directory")
    return physical_source
