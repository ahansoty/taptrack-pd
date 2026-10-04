#!/usr/bin/env bash
# TapTrack PD: one-command start (Git Bash on Windows, macOS, Linux).
#
#   ./start.sh            server + wrist bridge + Photon sidecar + Fetch.ai agent
#   ./start.sh --demo     same, with DEMO_MODE replay if the FREE-WILi is missing or unplugged
#   ./start.sh --no-agent / --no-photon / --seed (reload 14 days of synthetic data first)
#
# First run installs everything (Python venvs, npm package); later runs skip installs unless
# requirements change. Ctrl+C stops all processes.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
mkdir -p data

AGENT=1; PHOTON=1; SEED=0
for a in "$@"; do
  case "$a" in
    --demo) export DEMO_MODE=true ;;
    --no-agent) AGENT=0 ;;
    --no-photon) PHOTON=0 ;;
    --seed) SEED=1 ;;
    -h|--help) sed -n 2,10p "$0"; exit 0 ;;
  esac
done

PYBIN="$(command -v python3 || command -v python)"
venv_py() { if [ -x "$1/Scripts/python" ]; then echo "$1/Scripts/python"; else echo "$1/bin/python"; fi; }
stamp() { cat "$@" 2>/dev/null | cksum | cut -d' ' -f1; }

# ---------------------------------------------------------------- install (first run / changed reqs)
[ -d .venv ] || { echo "[setup] creating .venv"; "$PYBIN" -m venv .venv; }
PY="$(venv_py .venv)"
if [ "$(cat .venv/.stamp 2>/dev/null)" != "$(stamp requirements.txt)" ]; then
  echo "[setup] installing Python requirements"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt pytest
  # google-genai needs typing_extensions>=4.13; freewili pins 4.12.2 but works with newer (verified)
  "$PY" -m pip install -q -U "typing_extensions>=4.13" 2>/dev/null || true
  stamp requirements.txt > .venv/.stamp
fi
[ -f .env ] || { cp .env.example .env; echo "[setup] created .env from .env.example (fill in keys later)"; }

if [ "$AGENT" = 1 ]; then
  [ -d agent/.venv ] || { echo "[setup] creating agent/.venv"; "$PYBIN" -m venv agent/.venv; }
  APY="$(venv_py agent/.venv)"
  if [ "$(cat agent/.venv/.stamp 2>/dev/null)" != "$(stamp agent/requirements.txt)" ]; then
    echo "[setup] installing agent requirements"
    "$APY" -m pip install -q -r agent/requirements.txt
    stamp agent/requirements.txt > agent/.venv/.stamp
  fi
fi
if [ "$PHOTON" = 1 ]; then
  if command -v node >/dev/null; then
    [ -d photon/node_modules ] || { echo "[setup] npm install (photon)"; (cd photon && npm install --silent); }
  else
    echo "[warn] node not found: iMessage notifications disabled"; PHOTON=0
  fi
fi

# ---------------------------------------------------------------- run
PORT="${PORT:-$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)}"; PORT="${PORT:-8000}"
export PORT
PIDS=()
cleanup() {
  echo; echo "[stop] shutting down"
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

[ "$SEED" = 1 ] && "$PY" scripts/seed.py | tail -12

echo "[run] server on http://127.0.0.1:$PORT  (log: data/server.log)"
"$PY" -m taptrack.server > data/server.log 2>&1 &
PIDS+=($!)
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/api/status" >/dev/null || { echo "[error] server did not start; see data/server.log"; tail -20 data/server.log; exit 1; }

if [ "$PHOTON" = 1 ]; then
  echo "[run] Photon iMessage sidecar (log: data/photon.log)"
  TAPTRACK_URL="http://127.0.0.1:$PORT" node photon/sidecar.mjs > data/photon.log 2>&1 &
  PIDS+=($!)
fi
if [ "$AGENT" = 1 ]; then
  echo "[run] Fetch.ai agents (log: data/agent.log)"
  TAPTRACK_URL="http://127.0.0.1:$PORT" "$APY" -u agent/taptrack_agent.py > data/agent.log 2>&1 &
  PIDS+=($!)
  sleep 6
  grep -E "^taptrack-(care|clinic)|inspector|Mailbox" data/agent.log | head -5 || true
fi

echo
echo "  Clinician dashboard  http://127.0.0.1:$PORT/"
echo "  Caregiver view       http://127.0.0.1:$PORT/caregiver"
echo "  Wrist: blue = start a check, red = took meds, gray = cancel"
echo "  Ctrl+C to stop everything."
wait
