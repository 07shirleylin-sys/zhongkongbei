#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m app.server --host 0.0.0.0 --port 5000 --config config/local.json
