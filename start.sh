#!/usr/bin/env bash
set -euo pipefail

if [ ! -f frontend/dist/index.html ]; then
  echo "Built frontend is missing. Run ./install.sh first." >&2
  exit 1
fi

url="http://127.0.0.1:8000"
if curl --fail --silent "$url/api/health" >/dev/null 2>&1; then
  echo "Transcriber is already running at $url"
else
  .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 &
  app_pid=$!
  trap 'kill "$app_pid" 2>/dev/null || true' INT TERM EXIT
  ready=false
  for _ in $(seq 1 90); do
    if ! kill -0 "$app_pid" 2>/dev/null; then
      wait "$app_pid"
      exit $?
    fi
    if curl --fail --silent "$url/api/health" >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done
  if [ "$ready" != true ]; then
    echo "Transcriber did not become ready within 90 seconds." >&2
    exit 1
  fi
fi

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$url" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
  open "$url"
fi

if [ -n "${app_pid:-}" ]; then
  wait "$app_pid"
fi
