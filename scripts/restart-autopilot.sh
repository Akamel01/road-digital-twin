#!/bin/bash
# Restart the autopilot, but only after `twin pipeline preflight` passes (#199). Install as ~/bin/restart-autopilot.sh.
export TMPDIR=/data/tmp UV_CACHE_DIR=/data/uv-cache
export NUSCENES_VERSION=v1.0-trainval
export PATH=$HOME/.local/bin:$HOME/.local/node/bin:$PATH
LOG=/data/twin-dev/autopilot.log
cd ~/road-digital-twin || exit 1
if ! uv run --extra gpu twin pipeline preflight --store /data/twin-dev >> /data/twin-dev/preflight.log 2>&1; then
  echo "$(date -u +%FT%TZ) restart-autopilot: preflight FAILED, autopilot not started; see /data/twin-dev/preflight.log" | tee -a "$LOG"
  exit 1
fi
pkill -f "twin autopilo[t]"; sleep 2
nohup ~/bin/twin-autopilot.sh >> "$LOG" 2>&1 < /dev/null & disown
