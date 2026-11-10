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
