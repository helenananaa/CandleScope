#!/bin/sh
set -eu
ROOT=$(git rev-parse --show-toplevel)
OUT="$ROOT/output/large-interval-throughput-127-20261115"
RUN="$OUT/${1:-native-four-cold}"
test ! -e "$RUN"
mkdir -p "$RUN"
uptime > "$RUN/ambient-load-before.txt"
export CANDLESCOPE_PLAYWRIGHT_PACKAGE=/Users/ryanliang/.codex/worktrees/aggregation-closeout-20261112/CandleScope/output/aggregation-closeout-20261112/tooling/package.json
export CANDLESCOPE_QA_HTTP_PROXY=http://127.0.0.1:7897
export CANDLESCOPE_AGGREGATION_NATIVE_OUTPUT="$RUN"
export CANDLESCOPE_AGGREGATION_NATIVE_EXECUTABLE="$OUT/${CANDLESCOPE_QA_APP_CANDIDATE:-candidate}/CandleScope.app/Contents/MacOS/CandleScope"
export CANDLESCOPE_AGGREGATION_PACKAGE_REVISION=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["product_head"])' "$OUT/${CANDLESCOPE_QA_APP_CANDIDATE:-candidate}/package-source-manifest.json")
export CANDLESCOPE_AGGREGATION_REQUIRE_LIVE=true
node "$ROOT/docs/qa/large-interval-throughput-127-20261115/native.mjs" > "$RUN/driver.log" 2>&1
