#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment in .venv ..."
  python3 -m venv .venv
fi

source .venv/bin/activate

if [ ! -f ".venv/.deps_installed" ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  echo "Installing dependencies ..."
  pip install --upgrade pip
  pip install -r requirements.txt
  touch .venv/.deps_installed
fi

if [ ! -f ".env" ]; then
  echo "ERROR: .env file not found. Copy .env.example to .env and fill in your values."
  exit 1
fi

set -a
source .env
set +a

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo ""
echo "Cat_Scriber running at http://${HOST}:${PORT}"
echo "Press Ctrl-C to stop."
echo ""

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
