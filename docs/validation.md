# Executed validation — October 18, 2026

The following results describe the delivered local implementation, not untested planned features.

| Check | Executed command | Result |
|---|---|---|
| Backend, graph semantics, API, security, workers, durability, SSE | From backend: `$env:RUN_DOCKER_RESTART_TEST='1'; ..\.venv\Scripts\python.exe -m pytest -q` | **30 passed, 0 failed, 0 skipped**, 46.47 seconds; one dependency deprecation warning |
| Browser end to end against the Docker stack | From frontend: `npm test` | **3 passed, 0 failed**, 15.2 seconds |
| Production frontend | From frontend: `npm run build` | TypeScript and Vite build passed |
| Frontend lint | From frontend: `npm run lint` | Passed |
| Python lint | Root: `.\.venv\Scripts\ruff.exe check backend scripts` | Passed |
| Compose validation | `docker compose config --quiet` | Passed |
| Container build and startup | `docker compose --profile workers up -d --build` | Database, backend, frontend, and separate worker running; database/API health checks pass |
| HTTP controlled demo | `.\.venv\Scripts\python.exe scripts/demo.py` | Completed run `2eb03d59-fe7e-4c7a-990c-be243e3d74e8`; real failed first test attempt, passed second attempt, two stored recovery evidence sources |
| Query plans and timings | `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe scripts/benchmark.py` | Seven query types, 50 round trips each; actual results in query-timings.json |

## What the tests establish

- Real FalkorDB node/edge creation, range indexes, idempotent initialization, enforced unique IDs.
- Valid DAGs; missing dependencies, cycles, duplicate keys, and nonexistent tools rejected.
- Readiness from passed graph prerequisites, priority ordering, retry delay/budget, and resource availability.
- Two independent client connections race for a single step; exactly one claim and one Attempt are created.
- Stale fencing tokens, expired leases, repeated results, and invalid transitions rejected.
- Actual failing commands, restricted paths and commands, exact approved patch, independent test verification.
- Recovery inserts a graph prerequisite, preserves the original failure, verifies the procedure, and produces a checksum-backed artifact.
- Multi-hop impact, unaffected completed tasks, stale downstream verification, preserved prior verification records.
- Cross-session facts/events, procedure evidence, and isolated tenant graph reads.
- Actual separate worker process kill and restart; earlier successful work remains at one attempt.
- Database stop produces connection failures, then state survives restart and **container replacement**, with configured `/data` RDB persistence.
- Authenticated SSE replays persisted events; tenant/worker API authorization and validated public identifiers.
- Browser creation, status changes, graph rendering, failure history, decision evidence paths, memory, history, agent activity, settings, theme, mobile width, dialog escape, and reload persistence.

## Environment

Windows 11 (10.0.26200), native Python 3.12.10, Node 24.21.0, Docker Desktop Linux engine 29.8.2. Containers use Python 3.12-slim, Node 22-alpine for building, nginx 1.28-alpine for serving, and the pinned FalkorDB image in docker-compose.yml. The FalkorDB module reports version 4.22.1. Exact JavaScript package resolutions are in package-lock.json; Python direct dependencies are pinned in backend/requirements.txt.

Representative measured medians: run lookup 3.232 ms; step lookup 3.013 ms; readiness traversal 5.466 ms; multi-hop dependency traversal 8.778 ms. These are small synthetic graphs on this machine, including client/network overhead; they are not production throughput claims. Index-based lookup and traversal plans were captured from the database.

## Failures found during development

The first database startup relied on upstream CMD arguments that its entrypoint ignored. This prevented the intended password and persistence directory from taking effect. Compose now explicitly sets the executable and directory. Early generated sample runs were recreated after correcting the volume configuration.

The replacement test then exposed a SIGSEGV during AOF `GRAPH.EFFECT` replay of a constraint record in the pinned image. Database files were preserved locally before recovery from the existing RDB snapshot. The delivered stack uses RDB snapshots with synchronous checkpoint saves; the replacement regression passes with that configuration. AOF is **not** claimed to work. Related upstream reports exist, but an exact upstream diagnosis or fix is not claimed. See recovery-design.md for the durability tradeoff.

Graph export originally omitted outgoing relationships of shared Procedure and Agent nodes. Run-scoped exports now include applicable procedures and actual handoff paths. A browser-test locator also required disambiguation when multiple real runs shared a goal title. These issues were corrected before the final passing results above.

## Not established by these tests

No actual live model endpoint, public deployment, video recording, participant review, hostile-code OS sandbox, large-scale load behavior, automatic stale-result rebuilding, or paired backup/restore drill is claimed. The process crash test kills after claim and before command execution; it is not exhaustive fault injection at every instruction. RDB can lose writes after the last completed snapshot on abrupt database/host failure. Checkpoint acknowledgement performs SAVE, but zero-loss power-failure recovery is not claimed. The optional properties and reserved Fact-based decision relationship described in graph-schema.md are not all exercised by this demo.
