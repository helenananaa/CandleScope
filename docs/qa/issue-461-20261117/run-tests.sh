#!/bin/bash
set -euo pipefail
qa_repo=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$qa_repo"
qa_out=${1:-output/issue-461-20261117}
mkdir -p "$qa_out"
PYTHONPATH="$qa_repo/backend" "${CANDLESCOPE_QA_PYTHON:?Set CANDLESCOPE_QA_PYTHON to the test runtime}" -m pytest \
  backend/tests/test_warmup_revision_fence.py \
  backend/tests/test_native_history_range_fence.py \
  backend/tests/test_okx_history_range_fence.py \
  backend/tests/test_derived_history_range_fence.py \
  backend/tests/test_custom_materialization_ownership.py \
  backend/tests/test_mixed_backfill_pipeline.py \
  backend/tests/test_kline_revision_contract.py \
  backend/tests/test_source_revision_pipeline.py \
  backend/tests/test_default_mixed_history_query.py \
  backend/tests/test_mixed_history_reader.py \
  backend/tests/test_mixed_history_precedence.py \
  backend/tests/test_closed_target_snapshot.py \
  backend/tests/test_mixed_backfill_transport.py \
  backend/tests/test_mixed_backfill_cold_budget.py \
  backend/tests/test_history_archive_routing.py \
  backend/tests/test_history_fetch_stream_engine.py \
  backend/tests/test_query_cache_fencing.py \
  backend/tests/test_mixed_backfill_plan.py \
  -q --junitxml="$qa_out/acceptance-tests.xml"
