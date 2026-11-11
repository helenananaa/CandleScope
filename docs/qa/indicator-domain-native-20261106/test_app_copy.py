"""A candidate edit must never change its retained source app."""
import importlib.util
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS APFS candidate copier")
module_path = Path(__file__).with_name("app_copy.py")
spec = importlib.util.spec_from_file_location("qa_app_copy", module_path)
copier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(copier)


@pytest.mark.parametrize("linked_source", [False, True])
def test_candidate_edit_preserves_physical_source(tmp_path, linked_source):
    source = tmp_path / "retained.app"
    source.mkdir()
    (source / "backend.txt").write_text("retained")
    logical = tmp_path / "source-link.app"
    logical.symlink_to(source, target_is_directory=True)
    destination = tmp_path / "new" / "candidate.app"
    assert copier.clone_app(logical if linked_source else source, destination) == source
    assert destination.is_dir() and not destination.is_symlink()
    (destination / "backend.txt").write_text("candidate")
    assert (source / "backend.txt").read_text() == "retained"


@pytest.mark.parametrize("existing", ["directory", "symlink", "dangling"])
def test_existing_destination_is_never_replaced(tmp_path, existing):
    source = tmp_path / "source.app"
    source.mkdir()
    (source / "data").write_text("source")
    destination = tmp_path / "candidate.app"
    if existing == "directory":
        destination.mkdir()
        (destination / "data").write_text("local")
    else:
        destination.symlink_to(source if existing == "symlink" else tmp_path / "missing")
    with pytest.raises(FileExistsError):
        copier.clone_app(source, destination)
    assert (source / "data").read_text() == "source"
    assert destination.is_symlink() if existing != "directory" else (destination / "data").read_text() == "local"


def test_nested_candidate_is_rejected_before_creating_it(tmp_path):
    source = tmp_path / "source.app"
    source.mkdir()
    with pytest.raises(ValueError):
        copier.clone_app(source, source / "nested" / "candidate.app")
    assert list(source.iterdir()) == []
