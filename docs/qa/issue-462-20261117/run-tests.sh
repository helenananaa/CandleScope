#!/bin/bash
set -euo pipefail
qa_repo=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$qa_repo"
qa_out=${1:-output/issue-462-20261117}
mkdir -p "$qa_out"
PYTHONPATH="$qa_repo/backend" "${CANDLESCOPE_QA_PYTHON:?Set CANDLESCOPE_QA_PYTHON}" -m pytest \
  backend/tests/test_closed_component_retention.py \
  backend/tests/test_closed_component_retention_sources.py \
  backend/tests/test_consumer_recovery.py \
  backend/tests/test_deferred_component_preview.py \
  backend/tests/test_deferred_component_preview_continuation.py \
  backend/tests/test_deferred_component_preview_pipeline.py \
  backend/tests/test_deferred_component_preview_prefix.py \
  backend/tests/test_deferred_component_preview_source_window.py \
  backend/tests/test_deferred_component_preview_sources.py \
  backend/tests/test_forming_component_retention.py \
  backend/tests/test_forming_component_retention_sources.py \
  backend/tests/test_history_prefix.py \
  backend/tests/test_history_prefix_overlay.py \
  backend/tests/test_history_prefix_retention.py \
  backend/tests/test_history_prefix_runtime.py \
  backend/tests/test_kline_batch_source_recovery.py \
  backend/tests/test_kline_revision_contract.py \
  backend/tests/test_market_subscription_continuity.py \
  backend/tests/test_recovery_delivery_integration.py \
  backend/tests/test_recovery_kline_consumers.py \
  backend/tests/test_source_revision_pipeline.py \
  backend/tests/test_source_window_recovery.py \
  backend/tests/test_source_window_recovery_sources.py \
  backend/tests/test_subscription_continuity.py \
  -q --junitxml="$qa_out/acceptance-tests.xml"
