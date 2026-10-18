# Broken Application: Autonomous Diagnosis and Recovery

## Start

Copy `.env.example` to `.env`, start Docker Desktop, then run `docker compose up --build -d`. Open http://localhost:5173. The supplied demo tenant token is local-only; it is selected in the dashboard automatically. Alternate tokens can be entered under Settings.

## Dashboard walkthrough

1. Click **New agent run**. Keep the broken-application scenario and deterministic mode, then create and start.
2. Observe the persisted execution graph. Inspect the project task, then the failing calculator tests.
3. Recovery creates a repair task and a new dependency from the failed tests to the repair.
4. Open **Validate calculator**. Its attempt history contains the original real traceback, followed by a successful test attempt and independent verification output.
5. Open **Failure investigation**. The original failure remains visible as a verified recovery.
6. Open **Execution graph → Expand evidence**. Select the **apply approved patch** decision, then highlight its evidence path. Its Failure and Procedure sources were stored when recovery was chosen.
7. Use dependency impact in the step inspector to highlight actual multi-hop paths. Unaffected successful steps are listed separately.
8. Open Memory explorer to inspect the learned calculator fact and verified procedure. Open Run history to inspect checkpoint version and persisted goals.
9. Reload the page: state is read from FalkorDB.

The fixed plan is specifically for this scenario. A different free-text goal is retained as the run goal, but does not make deterministic mode a general-purpose planner.

## HTTP demonstration

With the backend running, from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/demo.py
```

Set `AGENTTRACE_TOKEN` when using a non-default tenant token. The script asserts a completed run, an actual failed first test attempt, a successful second attempt, and two stored recovery evidence sources.

## Crash and resume demonstration

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_restart.py -v -s
```

The test creates an isolated tenant, kills a real worker process after claim, restarts it, and asserts that completed work is not replayed. Its test graph is cleaned up afterward. For a judge-visible manual run, pause a run in the UI, stop the optional container worker (`docker compose stop worker`), disable the embedded worker (`EMBEDDED_WORKER=0` and restart backend), resume the run, then run the following from the native backend environment:

```powershell
..\.venv\Scripts\python.exe -u -m app.workers.runner --tenant demo --run RUN_UUID --owner crash-demo --claim-only
```

After it prints the claim, terminate that process. Wait longer than LEASE_MS, click Resume, then run:

```powershell
..\.venv\Scripts\python.exe -m app.workers.runner --tenant demo --run RUN_UUID --owner resumed-demo
```

The dashboard shows the interrupted attempt and reconciliation event. Finish recording with the graph evidence and verified results. A paused run lets in-flight tools finish but stops new claims.

For the all-Docker setup, set `EMBEDDED_WORKER=0` in `.env`, run `docker compose up -d --force-recreate backend`, and use `docker compose exec backend python -u -m app.workers.runner --tenant demo --run RUN_UUID --owner crash-demo --claim-only` for the first CLI command. Terminate that CLI process, then use the same `docker compose exec backend python -m app.workers.runner` prefix with `--owner resumed-demo` and without `--claim-only`. This keeps artifacts in the shared container workspace volume. Restore `EMBEDDED_WORKER=1` and recreate backend after the manual demonstration.
