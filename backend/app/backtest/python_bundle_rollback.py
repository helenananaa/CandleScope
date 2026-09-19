"""Schema v6/v7/v8/v9 rollback. Fails closed before dropping authoritative rows."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def rollback_python_bundles(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        version = int(
            connection.execute(
                "SELECT schema_version FROM backtest_schema_meta LIMIT 1"
            ).fetchone()[0]
        )
        if version not in {6, 7, 8, 9}:
            raise RuntimeError(
                "python bundle rollback requires exact schema version 6, 7, 8 or 9"
            )
        context_count = 0
        if version >= 7:
            context_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM backtest_research_launch_contexts"
                ).fetchone()[0]
            )
            if context_count:
                raise RuntimeError(
                    "python bundle rollback is fail-closed while research context rows exist"
                )
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM backtest_strategy_bundles"
            ).fetchone()[0]
        )
        if count:
            raise RuntimeError(
                "python bundle rollback is fail-closed while bundle rows exist"
            )
        connection.execute("BEGIN IMMEDIATE")
        if version == 9:
            from .report_storage import materialize_reports
            materialize_reports(connection)
        if version >= 8:
            from .checkpoint_history import materialize_histories
            materialize_histories(connection)
        if version >= 7:
            connection.execute(
                "DROP INDEX IF EXISTS idx_backtest_research_context_created"
            )
            connection.execute(
                "DROP TABLE IF EXISTS backtest_research_launch_contexts"
            )
        connection.execute("DROP TABLE IF EXISTS backtest_strategy_bundles")
        connection.execute(
            "UPDATE backtest_schema_meta SET schema_version = 5"
        )
        connection.commit()
        return {
            "schemaVersion": 5,
            "droppedBundles": True,
            "bundleRows": 0,
            "droppedResearchContexts": version >= 7,
            "researchContextRows": context_count,
        }
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
