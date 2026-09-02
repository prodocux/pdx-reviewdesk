#!/bin/sh
set -e
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
python="$root/.venv/bin/python"
if [ ! -x "$python" ]; then
  echo "Create .venv and pip install -e \".[dev]\" first." >&2
  exit 1
fi
exec "$python" -m uvicorn reviewdesk_api.main:app --reload --host 127.0.0.1 --port 8000
