#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: run_with_uppaal_blacklist_server.sh <command> [args...]" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    sudo kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  sudo fuser -k 80/tcp >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

sudo fuser -k 80/tcp >/dev/null 2>&1 || true
mkdir -p "$TMP_DIR/research/group/darts/uppaal/blacklist"
printf "OK: 4.0.12" > "$TMP_DIR/research/group/darts/uppaal/blacklist/index.html"

(
  cd "$TMP_DIR"
  sudo python3 -m http.server 80 >/tmp/codex_uppaal_http.log 2>&1
) &
SERVER_PID="$!"
sleep 1

"$@"
