# Recovery and restart design

## Failure recovery

The sample test command fails because `add(a,b)` subtracts. Independent verification runs a separate real unittest process. Recovery requires actual AssertionError output, the calculator test name, and the exact defective source precondition. It follows recorded Failure/Procedure evidence and inserts an approved repair step. The repair replaces only `return a - b` with `return a + b` in the isolated calculator.

The failed test depends on that repair, so it cannot run until the repair is verified. Retrying also requires an exponential delay and available attempt budget. An unknown signature is terminal for this controlled demo. The original failure and all attempt outputs remain in the graph after success.

## Crash recovery

Lease renewal occurs while a tool runs. On expiry, the current Attempt becomes interrupted and the Step becomes needs_reconciliation. A stale owner/token cannot finalize after that transition or after another claim.

Reconciliation uses current filesystem evidence for idempotent local patches and build artifacts. Interrupted reads and test commands may be retried because they have no external side effects. Unknown tool outcomes become failed for manual inspection and are never automatically retried. External publishing tools are not registered.

The automated test in `backend/tests/test_restart.py`:

1. Executes and verifies the first step.
2. Starts a separate worker process, which claims the test step and waits.
3. Terminates that process with the OS process kill operation.
4. Waits for its short test lease to expire.
5. Starts a fresh worker process against the same tenant/run.
6. Confirms reconciliation, successful continuation, retained interrupted attempt, and attempt_count=1 on the previously completed step.

This is a genuine process restart test. It interrupts after claim, before the subprocess action. It does not prove correctness for every possible crash instruction or external side effect. The included build and repair operations support read-before-retry, but there is no general distributed exactly-once side-effect guarantee.

## Database durability

Docker runs with append-only persistence on the named `agenttrace_data` volume. Compose explicitly starts `redis-server` with `--dir /data`, bypassing the upstream image's launcher so password, persistence, and directory arguments actually apply. Workspace artifacts use a second persistent volume. The opt-in database test checks the real server configuration, stops the container, confirms queries fail without fallback, starts it again, then **replaces the container** and verifies state survives through the named volume. Back up graph and workspaces together. No volume-deleting command is required for routine shutdown.
