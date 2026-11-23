#!/usr/bin/env bash
# Pure Docker smoke test; no host state, credentials or production Compose.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
docker build -t switchboard-tasks-test:local .
docker run --rm --network none \
  --mount "type=bind,src=$PWD/tests,dst=/app/tests,readonly" \
  --mount "type=bind,src=$PWD/scripts,dst=/app/scripts,readonly" \
  --entrypoint python switchboard-tasks-test:local \
  -m unittest discover -s /app/tests -p 'test_*.py' -v

# Exercise the single production runtime on both historical internal ports.
bash scripts/test_runtime.sh
