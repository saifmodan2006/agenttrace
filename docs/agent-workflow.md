# Agent workflow

1. Authenticated user submits a goal to `/api/runs`.
2. Planner validates a fixed demo plan or structured model response: registered tools, unique keys, valid dependencies, no cycles, bounded plan size, allowed arguments, supported success criteria.
3. The plan is written into the tenant's FalkorDB graph.
4. Start changes the run to running. Scheduler traverses DEPENDS_ON and checks retries, resources, and lease.
5. A single conditional write claims a step and creates its attempt, assignment, event, and scheduling decision.
6. Executor runs a fixed command vector or registered file operation in the per-run disposable workspace.
7. Verifier checks actual files or starts a fresh test subprocess. Tool-reported success alone is insufficient.
8. Failure is preserved with its output and signature. Recovery examines graph history and applicable procedures, then inserts the approved repair as a prerequisite when supported.
9. Verifier checks the repair, then rechecks the tests and artifact. The procedure becomes verified only after the original tests pass.
10. Each successful step saves a checkpoint. All steps verified means the run completes.

The roles are separate Python classes sharing the same memory manager. The embedded worker invokes them sequentially per task; independent worker processes can claim independent ready steps concurrently. They are not four independently model-powered autonomous services. This separation and the deterministic mode are intentional and visible.

Handoff records include the step/run, status, prior attempt IDs, expected output, pending role action, and failure evidence references. Executor → verifier and verifier → recovery handoffs are stored only when those actions occur. Agent activity shows stored heartbeats and last-seen state rather than fabricated ongoing activity.
