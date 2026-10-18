"""Restartable workers. API lifecycle and this CLI share the exact same engine."""

import argparse
import json
import logging
import signal
import threading
import time
from app.agents.recovery import RecoveryAgent
from app.agents.executor import ExecutorAgent
from app.agents.verifier import VerifierAgent
from app.core.config import settings
from app.memory.manager import AgentMemoryManager, Conflict
from app.tools.registry import ToolRegistry

log = logging.getLogger("agenttrace.worker")


class Worker:
    def __init__(self, memory, owner="executor", stop=None):
        self.memory = memory
        self.owner = owner
        self.stop = stop or threading.Event()
        self.memory.register_agent(owner)
        self.memory.register_agent("verifier", "verifier")

    def reconcile(self, run_id):
        self.memory.recover_interrupted_runs(run_id)
        for step in self.memory.steps(run_id):
            if step["status"] != "needs_reconciliation":
                continue
            registry = ToolRegistry(self.memory.tenant, run_id)
            registry.prepare()
            # Local, idempotent tools only. Never retry unknown external operations.
            if step["tool_name"] in {
                "apply_approved_patch",
                "build_project",
                "verify_file_exists",
                "inspect_artifact",
            }:
                passed, evidence, artifact = registry.verify(step)
                self.memory.reconcile(step["id"], passed, evidence, safe_retry=True, artifact=artifact)
            elif step["tool_name"] in {"read_file", "inspect_project", "run_tests", "run_allowed_command"}:
                self.memory.reconcile(
                    step["id"],
                    False,
                    {"summary": "Interrupted local read/test is safe to retry; no external side effect"},
                    safe_retry=True,
                )
            else:
                self.memory.reconcile(
                    step["id"], False, {"summary": "Unknown outcome requires manual reconciliation"}
                )

    def execute_claim(self, claim):
        step, attempt = claim["step"], claim["attempt"]
        done = threading.Event()
        stale = threading.Event()

        def renew():
            while not done.wait(max(settings.lease_ms / 3000, 0.1)):
                try:
                    self.memory.renew_lease(
                        step["id"], attempt["id"], self.owner, attempt["lease_token"], settings.lease_ms
                    )
                except Exception:
                    stale.set()
                    return

        renewal = threading.Thread(target=renew, daemon=True)
        renewal.start()
        try:
            self.memory.record_execution_event(
                step["run_id"], "attempt_started", step["title"], step["id"], attempt["id"], self.owner
            )
            try:
                result = ExecutorAgent(self.memory, self.owner).execute(step)
            except Exception as exc:
                result = {"exit_code": 1, "output": str(exc), "error": type(exc).__name__}
            if stale.is_set():
                raise Conflict("Lease lost during tool execution")
            self.memory.record_attempt_result(
                step["id"], attempt["id"], self.owner, attempt["lease_token"], result
            )
            self.memory.handoff_step(step["id"], self.owner, "verifier", "verifier")
            self.memory.record_execution_event(
                step["run_id"],
                "verification_started",
                "Independent verifier inspecting actual state",
                step["id"],
                attempt["id"],
                "verifier",
            )
            passed, evidence, artifact = VerifierAgent(self.memory).verify(step, result)
            self.memory.verify_step(
                step["id"], attempt["id"], self.owner, attempt["lease_token"], passed, evidence, artifact
            )
            if not passed:
                self.memory.handoff_step(step["id"], "verifier", "recovery", "recovery")
            else:
                if step["tool_name"] == "build_project":
                    resources = self.memory.store.nodes(
                        "MATCH (:Step {id:$id})-[:TARGETS]->(r:Resource) RETURN r", {"id": step["id"]}
                    )
                    self.memory.store_fact(
                        step["run_id"],
                        "calculator",
                        "verified result",
                        "add(2,3) = 5",
                        attempt["id"],
                        resources[0]["id"] if resources else None,
                    )
                self.memory.store_checkpoint(step["run_id"])
        finally:
            done.set()
            renewal.join(timeout=1)

    def tick(self, run_id=None):
        self.memory.heartbeat(self.owner)
        runs = [self.memory.get_run(run_id)] if run_id else self.memory.list_runs(limit=100)
        for run in runs:
            if self.stop.is_set():
                return False
            if run["status"] != "running":
                continue
            self.reconcile(run["id"])
            RecoveryAgent(self.memory).inspect(run["id"])
            ready = self.memory.get_ready_steps(run["id"])
            for candidate in ready:
                claim = self.memory.claim_step(
                    run["id"], candidate["step"]["id"], self.owner, settings.lease_ms
                )
                if claim:
                    self.execute_claim(claim)
                    self.memory.complete_run_if_done(run["id"])
                    return True
            steps = self.memory.steps(run["id"])
            if (
                any(s["status"] == "failed" for s in steps)
                and not ready
                and not any(
                    s["status"] in {"running", "verifying", "retryable", "needs_reconciliation"}
                    for s in steps
                )
            ):
                self.memory.store.query(
                    "MATCH (r:AgentRun {id:$run}) WHERE r.status='running' SET r.status='failed'",
                    {"run": run["id"]},
                )
        return False

    def loop(self):
        last_error = None
        while not self.stop.is_set():
            try:
                self.tick()
                last_error = None
            except Exception as exc:
                # DB outages stop scheduling; no hidden fallback. Persisted leases reconcile on return.
                signature = (type(exc).__name__, str(exc))
                if signature != last_error:
                    log.exception("Worker stopped this scheduling tick")
                last_error = signature
                self.stop.wait(2)
            self.stop.wait(settings.worker_poll_seconds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--owner", default="executor-cli")
    parser.add_argument("--run")
    parser.add_argument(
        "--claim-only", action="store_true", help="Claim then await termination for restart testing"
    )
    args = parser.parse_args()
    memory = AgentMemoryManager(args.tenant)
    worker = Worker(memory, args.owner)
    if args.claim_only:
        ready = memory.get_ready_steps(args.run)
        if not ready:
            raise RuntimeError("No eligible step")
        claim = memory.claim_step(args.run, ready[0]["step"]["id"], args.owner, settings.lease_ms)
        print(json.dumps(claim), flush=True)
        threading.Event().wait()
    else:
        signal.signal(signal.SIGINT, lambda *_: worker.stop.set())
        signal.signal(signal.SIGTERM, lambda *_: worker.stop.set())
        if args.run:
            while memory.get_run(args.run)["status"] == "running":
                worker.tick(args.run)
                time.sleep(settings.worker_poll_seconds)
        else:
            worker.loop()


if __name__ == "__main__":
    main()
