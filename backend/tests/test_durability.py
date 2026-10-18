import os
import subprocess
import time
from pathlib import Path
import pytest
from redis.exceptions import RedisError
from app.memory.manager import AgentMemoryManager


@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_RESTART_TEST") != "1", reason="Opt-in real local container stop/start"
)
def test_database_container_restart_persists_graph_and_stops_scheduling(memory, run):
    from app.workers.runner import Worker

    Worker(memory).tick(run["id"])
    assert memory.store.client.connection.config_get("appendonly")["appendonly"] == "yes"
    assert memory.store.client.connection.config_get("dir")["dir"] == "/data"
    before = memory.steps(run["id"])
    checkpoint = memory.checkpoint(run["id"])
    memory.store_fact(run["id"], "durability", "survives", "database restart", "test-verified-checkpoint")
    container = os.environ.get("FALKORDB_TEST_CONTAINER", "agenttrace-db")
    subprocess.run(["docker", "stop", container], check=True, capture_output=True, timeout=30)
    try:
        with pytest.raises(RedisError):
            disconnected = AgentMemoryManager(memory.tenant)
            disconnected.get_ready_steps(run["id"])
    finally:
        subprocess.run(["docker", "start", container], check=True, capture_output=True, timeout=30)
    deadline = time.monotonic() + 30
    while True:
        try:
            fresh = AgentMemoryManager(memory.tenant)
            fresh.store.ping()
            break
        except RedisError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    assert fresh.steps(run["id"]) == before
    assert fresh.checkpoint(run["id"])["id"] == checkpoint["id"]
    assert fresh.recall_facts(query="durability")[0]["value"] == "database restart"
    # Replacement discards the container's writable layer, proving the named
    # volume actually holds the authoritative data directory.
    subprocess.run(
        ["docker", "compose", "up", "-d", "--force-recreate", "falkordb"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        timeout=60,
    )
    deadline = time.monotonic() + 30
    while True:
        try:
            fresh = AgentMemoryManager(memory.tenant)
            fresh.store.ping()
            break
        except RedisError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    assert fresh.steps(run["id"]) == before
    assert fresh.checkpoint(run["id"])["id"] == checkpoint["id"]
    assert fresh.recall_facts(query="durability")[0]["value"] == "database restart"
