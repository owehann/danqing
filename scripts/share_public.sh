#!/usr/bin/env bash
# Zero-cost ($0) multi-user sharing launcher for Danqing Studio:
#   ./scripts/share_public.sh          -> Public HTTPS URL via Cloudflare Quick Tunnel (no account, $0)
#   ./scripts/share_public.sh --lan    -> Lab / campus Wi-Fi LAN URL (0.0.0.0:8765, $0)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${DANQING_PYTHON:-}" ]]; then
  PYTHON_BIN="${DANQING_PYTHON}"
elif [[ -x "${HOME}/miniforge3/envs/danqing/bin/python" ]]; then
  PYTHON_BIN="${HOME}/miniforge3/envs/danqing/bin/python"
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi
PORT="${DANQING_PORT:-8765}"
MODE="${1:---public}"

export PYTHONPATH="${REPO_ROOT}/core:${PYTHONPATH:-}"
cd "${REPO_ROOT}"

if [[ "${MODE}" == "--lan" ]]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo '127.0.0.1')"
  echo "=================================================================="
  echo " Danqing Studio (LAN Mode — Same Wi-Fi / Campus Network, \$0)"
  echo " Share with colleagues on the same network:"
  echo "   http://${LAN_IP}:${PORT}"
  echo " Privacy: RAM-only isolated sessions (--no-access-log)"
  echo "=================================================================="
  exec "${PYTHON_BIN}" -m uvicorn web.backend.app:app --host 0.0.0.0 --port "${PORT}" --no-access-log
fi

CACHE_DIR="${HOME}/.cache/danqing/bin"
CLOUDFLARED_BIN="${CACHE_DIR}/cloudflared"

if command -v cloudflared >/dev/null 2>&1; then
  CLOUDFLARED_BIN="$(command -v cloudflared)"
elif [[ ! -x "${CLOUDFLARED_BIN}" ]]; then
  mkdir -p "${CACHE_DIR}"
  OS_NAME="$(uname -s | tr '[:upper:]' '[:lower:]')"
  ARCH_NAME="$(uname -m)"
  if [[ "${OS_NAME}" == "darwin" ]]; then
    if [[ "${ARCH_NAME}" == "arm64" ]]; then
      CF_ASSET="cloudflared-darwin-arm64.tgz"
    else
      CF_ASSET="cloudflared-darwin-amd64.tgz"
    fi
    echo "[Danqing] Downloading official cloudflared (${CF_ASSET}) to ${CACHE_DIR}..."
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${CF_ASSET}" -o "${CACHE_DIR}/cf.tgz"
    tar -xzf "${CACHE_DIR}/cf.tgz" -C "${CACHE_DIR}"
    rm -f "${CACHE_DIR}/cf.tgz"
    chmod +x "${CLOUDFLARED_BIN}"
  else
    if [[ "${ARCH_NAME}" == "aarch64" || "${ARCH_NAME}" == "arm64" ]]; then
      CF_ASSET="cloudflared-linux-arm64"
    else
      CF_ASSET="cloudflared-linux-amd64"
    fi
    echo "[Danqing] Downloading official cloudflared (${CF_ASSET}) to ${CACHE_DIR}..."
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/${CF_ASSET}" -o "${CLOUDFLARED_BIN}"
    chmod +x "${CLOUDFLARED_BIN}"
  fi
fi

# Start Uvicorn locally if port is not already bound
SERVER_PID=""
if ! lsof -iTCP:"${PORT}" -sTCP:LISTEN -t >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m uvicorn web.backend.app:app --host 127.0.0.1 --port "${PORT}" --no-access-log &
  SERVER_PID=$!
  trap '[[ -n "${SERVER_PID}" ]] && kill "${SERVER_PID}" 2>/dev/null || true' EXIT INT TERM
  sleep 1.5
fi

echo "=================================================================="
echo " Danqing Studio — Starting \$0 Public HTTPS Tunnel (Zero Account)"
echo " Look for the https://*.trycloudflare.com link printed below."
echo " Press Ctrl+C at any time to close the public link immediately."
echo "=================================================================="

exec "${CLOUDFLARED_BIN}" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}"
