import json
import os
import subprocess
import sys
import time
from pathlib import Path
from app.core.config import settings
from app.memory.manager import AgentMemoryManager
from app.workers.runner import Worker


def test_real_executor_process_crash_and_restart(memory, run, monkeypatch):
    # Finish inspect first, then kill a different OS process with a live task lease.
    Worker(memory).tick(run["id"])
    completed = next(s for s in memory.steps(run["id"]) if s["key"] == "inspect")
    monkeypatch.setattr(settings, "lease_ms", 700)
    env = {**os.environ, "LEASE_MS": "700", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    p = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "app.workers.runner",
            "--tenant",
            memory.tenant,
            "--run",
            run["id"],
            "--owner",
            "crash-worker",
            "--claim-only",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = p.stdout.readline()
        assert line, p.stderr.read()
        claim = json.loads(line)
        assert claim["step"]["status"] == "running"
        p.kill()
        p.wait(timeout=10)
        time.sleep(0.8)
        resumed = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.workers.runner",
                "--tenant",
                memory.tenant,
                "--run",
                run["id"],
                "--owner",
                "restart-worker",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert resumed.returncode == 0, resumed.stderr
        fresh = AgentMemoryManager(memory.tenant)
        assert fresh.get_run(run["id"])["status"] == "completed"
        assert fresh.get_step(completed["id"])["attempt_count"] == 1
        attempts = fresh.attempts(claim["step"]["id"])
        assert attempts[0]["status"] == "interrupted"
        assert len(attempts) >= 2
        assert any(e["event_type"] == "reconciliation_completed" for e in fresh.events(run["id"], limit=500))
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
