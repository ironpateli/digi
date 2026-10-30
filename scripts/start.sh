#!/bin/sh
set -e
python -m app.seed --if-empty
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
