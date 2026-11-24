# Box job queue and worker

The queue keeps the box busy (ADR 0005). Jobs are JSON files in `<store>/queue/{pending,running,done,failed}/`; a job moves between folders by atomic rename. One worker runs one job at a time, through the normal runner and its run lock.

## Queue a job

`job.json`:

```json
{"type": "run", "scene": "scene-0757", "eval": true}
```

| type | fields |
|---|---|
| `run` | `scene`; optional `pipeline`, `params` (inline mapping or a yaml path) |
| `rerun` | `run_id`, `from_stage`; optional `pipeline`, `params` |
| `eval` | `run_id`; optional `baseline`, `rerun` |

`"eval": true` on a run or rerun job runs `twin eval` on the new run afterwards. While `twin eval` (#149) is not merged, that step is recorded as `skipped`.

```
uv run twin queue add job.json --store /data/twin-dev
uv run twin queue ls --store /data/twin-dev
```

`ls` prints state, job id, type, run id and the error or eval result (`eval_result`). The full record (times, run id, error) is the job file.

## Start and stop the worker (box)

```
cd ~/road-digital-twin   # the checkout the worker should run
nohup uv run twin worker --store /data/twin-dev > /data/twin-dev/worker.log 2>&1 &
tail -f /data/twin-dev/worker.log
```

Stop: `pkill -f "twin worker"`. A job in flight is put back to `pending` at the next worker start (and its half-finished run is marked interrupted by the existing run recovery), so a stop or a crash loses nothing. Only one worker can run; a second exits with code 3.

`--jobs N` stops after N jobs (default 0: run until stopped). `--poll S` is the idle wait (default 30 s).

## Rules the worker follows

- Before each job it checks free disk. It holds the job (leaves it `pending`, logs "held") when `/` has less than 10 GB or `/data` less than 50 GB free. The thresholds are `DISK_RULES` in `twin/jobqueue.py`.
- A job whose run has a failed stage, or that raises, goes to `failed` with the error. An eval no-go is a result: the job is `done` with `eval_result: no-go`.
- If another run holds the run store lock, the job is put back and tried again later.

Starting at boot (systemd, crontab `@reboot`) is the operator's choice; none is installed.

## Memory caps and headroom (#451)

| job kind | default cap | override |
|---|---|---|
| area merge (P2 shell: `area merge && area twin && eval`) | 20 GB | `TWIN_MEM_CAP_AREA_MERGE_GB` |
| per-drive stage (streaming child) | 8 GB | `TWIN_MEM_CAP_STAGE_GB`, `TWIN_MEM_CAP_STAGE_<NAME>_GB` |
| eval / publish / prgate task | 8 GB | `TWIN_MEM_CAP_EVAL_GB`, `TWIN_MEM_CAP_PUBLISH_GB`, `TWIN_MEM_CAP_PRGATE_GB` |

A queue job may set `"mem_cap_gb": <number>`; it wins over the env var and the default. A
non-numeric, boolean or non-positive override is ignored with one warning and the default applies.
`mem_cap_gb` is optional and additive: in streaming mode it caps **each** stage child, so it applies
per task; in serial mode it has no effect. `twin area build` has no worker call site and no cap
setting; run it by hand under the same wrapper:

    systemd-run --user --scope --quiet -p MemoryMax=8G -p MemorySwapMax=0 -- uv run twin area build <name> --store <store>

How it is applied: the detached area shell runs as `systemd-run --user --scope --quiet -p
MemoryMax=<bytes> -p MemorySwapMax=0 -- ...`, so the whole `merge && twin && eval` tree shares one
cap. Each streaming stage child creates `twin-cap-<key>/` (key includes a per-attempt uuid) in the
nearest ancestor cgroup that delegates `memory`, writes `memory.max` and `memory.swap.max=0`, and
moves itself in; forked pools inherit it. Swap is off, so an over-cap child is killed, not swapped;
each streaming child is bounded and the scheduler's admission budget remains the aggregate control.

Not capped: the serial `twin worker` runs jobs in-process; start the box worker with
`twin worker --stream` so each stage child gets a cap.

Prerequisite: a user systemd session with the `memory` controller delegated. Start the streaming
worker (`twin worker --stream`; its scheduler prints the line at start, even with an empty queue) and
read its one `twin memcap:` line: `shell=systemd-run` and `child-cgroups=<root>` means both
mechanisms work; `shell=UNCAPPED` or `child-cgroups=none` names the unavailable one and the
`WARNING` suffix says caps are not enforced and every affected job runs uncapped. For a boot worker
without a login session, `loginctl enable-linger <user>` (this does not change SSH settings).

Headroom: before the P2 area merge, `MemAvailable` must be at least the cap + 10 GB (the `available`
column of `free -g`; 30 GB with the default 20 GB cap). Otherwise autopilot logs `autopilot: held:
area-merge needs 20.0 GB cap + 10.0 GB headroom; 24.3 GB available`, leaves the commit unbuilt and
retries on the next pass; nothing is pulled, queued or published. The same rule applies to a manual
area build (8 GB cap + 10 GB headroom).

Cap kill: a streaming job whose child hits its cap ends `failed` with `error: "oom-cap"`; the
scheduler logs `failed <id> oom-cap` and carries on with other jobs. An autopilot P2 shell is
recorded as `exit: "oom-cap"` only when its exit file is missing or holds a code other than `0`/`1`
**and** its log shows OOM text; a stored `0` or `1` is never overridden. It is not published and is
not retried for that commit — clear `p2.built` in `<store>/autopilot/state.json` to retry. `oom-cap`
comes only from a job's own cgroup `memory.events` (`oom_kill > 0`) or OOM text in the autopilot
shell log; a bare SIGKILL/137 is not `oom-cap`.

The worker's parent process holds only its fd/pipe overhead, not job memory; only the streaming
child is capped and killed. Stopping: `pkill -f "twin worker"` (SIGTERM) matches the worker and its
forked stage child — they share the argv — so both exit and the job is recovered on the next start. A
`SIGKILL` of the worker alone cannot run the child's cleanup: the child keeps the inherited
`.worker.lock` until it exits, so check `pgrep -f "twin worker"` before restarting (a restart while
it lives exits 3). No SIGTERM handler is needed.

Preflight exception (#451, deliberate, no code change): `scripts/restart-autopilot.sh` runs `twin
pipeline preflight`, whose `twin_cli("area", "merge", ...)` starts a real 2-drive area merge outside
the gate; use the manual wrapper (`systemd-run ... twin area merge`) if needed.

Crontab, SSH settings and the `sme_*` (Librarian) containers are unchanged.

## Method-PR gate (`twin-gates`, #154)

A PR labelled `method` is run on scene-0757 and compared with the best main run (ADR 0005). `twin prgate poll` lists the open `method` PRs with `gh` and queues one `prgate` job per new head commit (a head that already has a job is skipped, so it reruns only when the head changes). The worker runs the job: it clones the PR into `~/rdt-prgate/<pr>` (never `~/road-digital-twin`), runs scene-0757 there into `~/rdt-prgate/<pr>-runs`, runs `twin eval` with the worker's code against the baseline, then posts one PR comment (edited on later heads) and the commit status `twin-gates`.

- Baseline: the finished scene-0757 run in the worker's store with a go verdict (`gates.json`), else the fewest no-go checks, newest first.
- Status: `success` for go (and for "not measured", which blocks only publishing), `failure` for no-go, `error` when the gate itself failed, `pending` while it runs.
- Try without posting: `uv run twin prgate run <pr> <head-sha> --dry-run --store /data/twin-dev` (clones and runs, prints the comment and statuses). `twin prgate poll --dry-run` only lists.
- The box needs `gh` installed and authenticated (`gh auth login`, a token with `repo` scope: comments and commit statuses). Run the poll from cron, for example every 5 minutes: `*/5 * * * * cd ~/road-digital-twin && ~/.local/bin/uv run twin prgate poll --store /data/twin-dev >> /data/twin-dev/prgate.log 2>&1`. The worker must be restarted onto the code that knows `prgate` jobs.
- Open PRs without the label get `twin-gates` = success ("n/a: not a method PR") at each poll, so requiring the check does not block them. A new PR waits "Expected" until the next poll (at most the cron interval).
- Block the merge (operator, repo settings, not done by the agents): Settings > Branches > branch protection rule for `main` > tick "Require status checks to pass before merging" > search and add `twin-gates`. A no-go (`failure`) then blocks the merge button.
