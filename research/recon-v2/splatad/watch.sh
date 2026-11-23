#!/bin/sh
# emit progress every 5000 steps, errors, OOM, container end
C=$1
docker logs -f $C 2>&1 | tr "\r" "\n" | python3 -u -c "
import sys,re
nxt=10000
for l in sys.stdin:
    m=re.match(r\"(\d+) \(\",l)
    if m and int(m[1])>=nxt: print(\"step\",l.strip()[:90],flush=True); nxt+=5000
    if re.search(r\"Traceback|Error|out of memory|Killed\",l) and \"Warning\" not in l: print(\"ERROR\",l.strip()[:200],flush=True)
"
echo "END $(docker inspect -f "OOM={{.State.OOMKilled}} exit={{.State.ExitCode}}" $C)"
