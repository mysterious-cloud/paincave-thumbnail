#!/usr/bin/env bash
# Pain Cave Thumbnail — generation CLI wrapper
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --project "$PROJECT_DIR" python "$PROJECT_DIR/src/generate.py" "$@"
