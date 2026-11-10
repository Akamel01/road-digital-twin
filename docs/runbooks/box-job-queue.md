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

## Method-PR gate (`twin-gates`, #154)

A PR labelled `method` is run on scene-0757 and compared with the best main run (ADR 0005). `twin prgate poll` lists the open `method` PRs with `gh` and queues one `prgate` job per new head commit (a head that already has a job is skipped, so it reruns only when the head changes). The worker runs the job: it clones the PR into `~/rdt-prgate/<pr>` (never `~/road-digital-twin`), runs scene-0757 there into `~/rdt-prgate/<pr>-runs`, runs `twin eval` with the worker's code against the baseline, then posts one PR comment (edited on later heads) and the commit status `twin-gates`.

- Baseline: the finished scene-0757 run in the worker's store with a go verdict (`gates.json`), else the fewest no-go checks, newest first.
- Status: `success` for go (and for "not measured", which blocks only publishing), `failure` for no-go, `error` when the gate itself failed, `pending` while it runs.
- Try without posting: `uv run twin prgate run <pr> <head-sha> --dry-run --store /data/twin-dev` (clones and runs, prints the comment and statuses). `twin prgate poll --dry-run` only lists.
- The box needs `gh` installed and authenticated (`gh auth login`, a token with `repo` scope: comments and commit statuses). Run the poll from cron, for example every 5 minutes: `*/5 * * * * cd ~/road-digital-twin && ~/.local/bin/uv run twin prgate poll --store /data/twin-dev >> /data/twin-dev/prgate.log 2>&1`. The worker must be restarted onto the code that knows `prgate` jobs.
- Block the merge (operator, repo settings, not done by the agents): Settings > Branches > main > "Require status checks to pass before merging" > add `twin-gates`. A PR that is not labelled `method` has no `twin-gates` status and would be blocked too, so use a ruleset that targets only the paths the methods live in, or leave the check unrequired and rely on the review; GitHub has no label-conditional required check.
