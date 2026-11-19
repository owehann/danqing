#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${DANQING_PYTHON:-}" ]]; then
  PYTHON_BIN="${DANQING_PYTHON}"
elif [[ -x "${HOME}/miniforge3/envs/danqing/bin/python" ]]; then
  PYTHON_BIN="${HOME}/miniforge3/envs/danqing/bin/python"
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi
HOST="${DANQING_HOST:-127.0.0.1}"
PORT="${DANQING_PORT:-8765}"

if [[ "${1:-}" == "--restart" ]]; then
  shift
  LISTEN_PIDS="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${LISTEN_PIDS}" ]]; then
    kill ${LISTEN_PIDS} 2>/dev/null || true
    sleep 0.5
    REMAINING_PIDS="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${REMAINING_PIDS}" ]]; then
      kill -9 ${REMAINING_PIDS} 2>/dev/null || true
      sleep 0.2
    fi
  fi
fi

export PYTHONPATH="${REPO_ROOT}/core:${PYTHONPATH:-}"
cd "${REPO_ROOT}"

exec "${PYTHON_BIN}" -m uvicorn web.backend.app:app --host "${HOST}" --port "${PORT}" --no-access-log "$@"
