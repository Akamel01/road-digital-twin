#!/bin/bash
# Keep the twin worker, autopilot and telemetry running, and run `twin health` once a minute.
# Install: cp scripts/twin-supervisor.sh ~/bin/ ; start at boot with the @reboot line in the PR.
# Config (env): SUP_CONF file of "name|pgrep pattern|start command|log file" lines (default: the
# three box services), SUP_INTERVAL whole seconds between checks (15), SUP_LOG, SUP_RESTARTS (a line
# "<utc iso> <name>" per restart, read by `twin health`), SUP_HEALTH command run each minute.
# A dead service is restarted after a backoff of 2, 4, ... 300 s while it keeps dying within
# 120 s of its start. Patterns use the [x] trick so they never match this script.
# Bash 3.2 compatible (the tests run on a Mac).
STORE=${SUP_STORE:-/data/twin-dev}
INTERVAL=${SUP_INTERVAL:-15}
LOG=${SUP_LOG:-$STORE/supervisor.log}
RESTARTS=${SUP_RESTARTS:-$STORE/supervisor-restarts.log}
HEALTH=${SUP_HEALTH-cd \$HOME/road-digital-twin && .venv/bin/twin health --store $STORE}
CONF=${SUP_CONF:-}
DEFAULT="worker|venv/bin/twin worke[r]|\$HOME/bin/twin-worker.sh|$STORE/worker.log
autopilot|twin autopilo[t]|\$HOME/bin/twin-autopilot.sh|$STORE/autopilot.log
telemetry|twin box monito[r]|\$HOME/bin/twin-telemetry.sh|$STORE/telemetry.log"
[ -n "$CONF" ] && DEFAULT=$(cat "$CONF")

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%S+00:00) supervisor: $*" >> "$LOG"; }
mkdir -p "$(dirname "$LOG")"

names=(); pats=(); cmds=(); logs=(); fails=(); started=(); due=()
while IFS='|' read -r n p c l; do
  [ -z "$n" ] && continue
  names+=("$n"); pats+=("$p"); cmds+=("$c"); logs+=("$l"); fails+=(0); started+=(0); due+=(0)
done <<< "$DEFAULT"

say "start, watching: ${names[*]}"
tick=0
while :; do
  now=$(date +%s)
  for i in "${!names[@]}"; do
    pgrep -f "${pats[$i]}" > /dev/null && continue
    [ "$now" -lt "${due[$i]}" ] && continue
    # it died: a long-lived one resets the backoff
    if [ $((now - ${started[$i]})) -gt 120 ]; then fails[$i]=0; fi
    fails[$i]=$((${fails[$i]} + 1))
    wait_s=$((2 ** ${fails[$i]})); [ "$wait_s" -gt 300 ] && wait_s=300
    nohup bash -c "${cmds[$i]}" >> "${logs[$i]}" 2>&1 < /dev/null &
    disown 2> /dev/null
    started[$i]=$now; due[$i]=$((now + wait_s))
    say "${names[$i]} was down: restarted (attempt ${fails[$i]}, next restart not before ${wait_s}s)"
    echo "$(date -u +%Y-%m-%dT%H:%M:%S+00:00) ${names[$i]}" >> "$RESTARTS"
  done
  tick=$((tick + INTERVAL))
  if [ -n "$HEALTH" ] && [ "$tick" -ge 60 ]; then
    tick=0
    (timeout 120 bash -c "$HEALTH" >> "$LOG" 2>&1 &)
  fi
  [ -n "$SUP_ONCE" ] && exit 0
  sleep "$INTERVAL"
done
