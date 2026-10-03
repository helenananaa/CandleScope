from pathlib import Path

import pytest

from scripts.check_architecture import dependency_graph, training_violations


def test_replay_responsibilities_keep_their_dependency_direction():
    root = Path(__file__).resolve().parents[1] / "app"
    assert training_violations(root, dependency_graph(root)) == []


def check_fixture(tmp_path, source, owner="persistence/ledger"):
    root = tmp_path / "app"
    path = root / "replay/training" / (owner + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return training_violations(root, dependency_graph(root))


@pytest.mark.parametrize("source", [
    "from ..storage import TrainingRunStore",
    "from ..service import TrainingRunService",
    "from ..repositories.runs import TrainingRunRepository",
    "from ..ordered_playback import TrainingOrderedPlayback",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ..storage import TrainingRunStore",
    "from importlib import import_module as load\nload('app.replay.training.service')",
])
def test_operations_cannot_reach_back_to_owners(tmp_path, source):
    assert check_fixture(tmp_path, source)


@pytest.mark.parametrize("source", [
    "def write(connection):\n    connection.commit()",
    "def write(connection):\n    connection.rollback()",
    "def write(connection):\n    with connection:\n        pass",
    "def write(connection):\n    connection.execute('BEGIN IMMEDIATE')",
    "def write(connection):\n    connection.executescript('SELECT 1; COMMIT;')",
    "import sqlite3 as db\ndb.connect('other.db')",
    "from sqlite3 import connect as open_db\nopen_db('other.db')",
    "from app.replay.storage.sqlite_store import ReplaySQLiteStore as Store\nStore('other.db')",
    "from concurrent.futures import ThreadPoolExecutor as Pool\nPool()",
])
@pytest.mark.parametrize("owner", ["persistence/ledger", "repositories/runs"])
def test_lower_owners_cannot_create_an_independent_transaction(tmp_path, source, owner):
    assert check_fixture(tmp_path, source, owner)


@pytest.mark.parametrize("source", [
    "async def write(connection):\n    return 1",
    "def write(connection, store):\n    store.run_extension_write(lambda c: None)",
    "def write(connection, actor):\n    actor.publish()",
    "import asyncio\nasyncio.create_task(write())",
])
def test_operations_cannot_escape_the_callers_transaction(tmp_path, source):
    assert check_fixture(tmp_path, source)


def test_reexports_cannot_hide_reverse_replay_dependencies(tmp_path):
    check_fixture(tmp_path, "from ..helper import callback")
    helper = tmp_path / "app/replay/training/helper.py"
    helper.write_text("from .service import TrainingRunService as callback", encoding="utf-8")
    root = tmp_path / "app"
    assert training_violations(root, dependency_graph(root))


@pytest.mark.parametrize("owner, source", [
    ("admission_rules", "from .storage import TrainingRunStore"),
    ("order_rules", "from .persistence.ledger import append_contract_ledger"),
    ("ordered_playback", "from .service import TrainingRunService"),
    ("advance_service", "from .service import TrainingRunService"),
    ("review_service", "from .service import TrainingRunService"),
    ("persistence/ledger", "from ..advance_service import TrainingAdvanceService"),
    ("repositories/runs", "from ..review_service import TrainingReviewService"),
])
def test_rule_and_application_components_have_no_facade_back_reference(tmp_path, owner, source):
    assert check_fixture(tmp_path, source, owner)


def test_operations_can_share_a_connection_without_owning_its_lifecycle(tmp_path):
    assert check_fixture(tmp_path, "def write(connection):\n    connection.execute('INSERT INTO ledger VALUES (?)', (1,))") == []
    assert check_fixture(tmp_path, "def submit(self, write):\n    return self.base_store.run_extension_write(write)", "repositories/runs") == []
