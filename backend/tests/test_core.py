import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from redis.exceptions import ResponseError
from app.graph.store import now, uid
from app.memory.manager import AgentMemoryManager, Conflict, NotFound
from app.models.schemas import Plan, StepSpec, TRANSITIONS
from app.tools.registry import ToolRegistry
from app.workers.runner import Worker


def first(memory, run):
    return memory.get_ready_steps(run["id"])[0]["step"]


def claim(memory, run, owner="test-worker", lease_ms=15000):
    memory.register_agent(owner)
    s = first(memory, run)
    return memory.claim_step(run["id"], s["id"], owner, lease_ms)


def test_graph_initialization_indexes_and_constraints(memory):
    memory.initialize()
    assert memory.store.ping()
    indexes = memory.store.query("CALL db.indexes()", read=True)
    assert {"AgentRun", "Step", "Attempt", "Failure"} <= {r[0] for r in indexes}
    memory.create_run("Unique IDs are enforced")
    run = memory.list_runs()[0]
    with pytest.raises(ResponseError):
        memory.store.query("CREATE (:AgentRun {id:$id})", {"id": run["id"]})


def test_plan_creates_real_graph(memory, run):
    graph = memory.get_execution_graph(run["id"])
    assert len([n for n in graph["nodes"] if n["label"] == "Step"]) == 5
    assert {"HAS_STEP", "DEPENDS_ON", "TARGETS"} <= {e["label"] for e in graph["edges"]}


@pytest.mark.parametrize(
    "steps",
    [
        [{"key": "a", "title": "A", "objective": "A", "tool_name": "read_file", "depends_on": ["missing"]}],
        [{"key": "a", "title": "A", "objective": "A", "tool_name": "arbitrary_shell"}],
        [{"key": "a", "title": "A", "objective": "A", "tool_name": "read_file", "depends_on": ["a"]}],
        [
            {"key": "a", "title": "A", "objective": "A", "tool_name": "read_file", "depends_on": ["b"]},
            {"key": "b", "title": "B", "objective": "B", "tool_name": "read_file", "depends_on": ["a"]},
        ],
        [
            {"key": "a", "title": "A", "objective": "A", "tool_name": "read_file"},
            {"key": "a", "title": "B", "objective": "B", "tool_name": "read_file"},
        ],
    ],
)
def test_reject_invalid_plans(steps):
    with pytest.raises(ValidationError):
        Plan.model_validate({"steps": steps})


def test_ready_excludes_unsatisfied_dependencies(memory, run):
    assert [r["step"]["key"] for r in memory.get_ready_steps(run["id"])] == ["inspect"]
    Worker(memory).tick(run["id"])
    assert [r["step"]["key"] for r in memory.get_ready_steps(run["id"])] == ["tests", "source"]


def test_retry_delay_and_budget(memory, run):
    s = first(memory, run)
    memory.store.query(
        "MATCH (s:Step {id:$id}) SET s.status='retryable',s.retry_after_ms=$future",
        {"id": s["id"], "future": now() + 100000},
    )
    assert not memory.get_ready_steps(run["id"])
    memory.store.query(
        "MATCH (s:Step {id:$id}) SET s.retry_after_ms=0,s.attempt_count=s.max_attempts", {"id": s["id"]}
    )
    assert not memory.get_ready_steps(run["id"])


def test_resources_unavailable_excluded(memory, run):
    memory.store.query("MATCH (r:Resource) SET r.available=false")
    assert not memory.get_ready_steps(run["id"])
    memory.register_agent("worker")
    s = memory.steps(run["id"])[0]
    assert memory.claim_step(run["id"], s["id"], "worker") is None


def test_atomic_concurrent_claims(memory, run):
    s = first(memory, run)
    barrier = threading.Barrier(2)
    for name in ["worker-a", "worker-b"]:
        memory.register_agent(name)

    def race(name):
        other = AgentMemoryManager(memory.tenant)
        barrier.wait()
        return other.claim_step(run["id"], s["id"], name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(race, ["worker-a", "worker-b"]))
    assert sum(r is not None for r in results) == 1
    assert len(memory.attempts(s["id"])) == 1


def test_stale_worker_and_duplicate_result_rejected(memory, run):
    c = claim(memory, run)
    s, a = c["step"], c["attempt"]
    result = {"exit_code": 0, "output": "Files inspected"}
    with pytest.raises(Conflict):
        memory.record_attempt_result(s["id"], a["id"], "test-worker", "wrong-token", result)
    memory.record_attempt_result(s["id"], a["id"], "test-worker", a["lease_token"], result)
    with pytest.raises(Conflict):
        memory.record_attempt_result(s["id"], a["id"], "test-worker", a["lease_token"], result)
    with pytest.raises(Conflict):
        memory.transition(s["id"], "pending", "test-worker", a["lease_token"], a["id"])


def test_lease_expiry_and_new_fence(memory, run):
    c = claim(memory, run)
    s, a = c["step"], c["attempt"]
    memory.store.query("MATCH (s:Step {id:$id}) SET s.lease_until_ms=0", {"id": s["id"]})
    interrupted = memory.recover_interrupted_runs(run["id"])
    assert interrupted[0]["status"] == "needs_reconciliation"
    with pytest.raises(Conflict):
        memory.renew_lease(s["id"], a["id"], "test-worker", a["lease_token"])
    Worker(memory).reconcile(run["id"])
    fresh = memory.claim_step(run["id"], s["id"], "test-worker")
    assert fresh["attempt"]["lease_token"] != a["lease_token"]
    with pytest.raises(Conflict):
        memory.record_attempt_result(
            s["id"], a["id"], "test-worker", a["lease_token"], {"exit_code": 0, "output": "old"}
        )


def test_pause_prevents_claiming(memory, run):
    memory.set_run_status(run["id"], "paused")
    assert not memory.get_ready_steps(run["id"])
    memory.set_run_status(run["id"], "running")
    assert memory.get_ready_steps(run["id"])


def test_unknown_outcome_never_retried(memory, run):
    c = claim(memory, run)
    memory.store.query(
        "MATCH (s:Step {id:$id}) SET s.tool_name='external_publish',s.lease_until_ms=0",
        {"id": c["step"]["id"]},
    )
    Worker(memory).reconcile(run["id"])
    assert memory.get_step(c["step"]["id"])["status"] == "failed"


def test_tool_sandbox_and_real_failure(memory, run):
    registry = ToolRegistry(memory.tenant, run["id"])
    with pytest.raises(ValueError):
        registry.execute("read_file", {"path": "../../.env"})
    with pytest.raises(ValueError):
        registry.execute("run_allowed_command", {"command": "echo hacked"})
    with pytest.raises(ValueError):
        registry.execute("apply_approved_patch", {"patch": "arbitrary"})
    result = registry.execute("run_tests", {})
    assert result["exit_code"] != 0 and "AssertionError" in result["output"]
    result = registry.execute("apply_approved_patch", {})
    assert result["exit_code"] == 0
    assert registry.execute("run_tests", {})["exit_code"] == 0
    assert "already present" in registry.execute("apply_approved_patch", {})["output"]


def test_verifier_rejects_fabricated_tool_success(memory, run):
    registry = ToolRegistry(memory.tenant, run["id"])
    registry.prepare()
    step = next(s for s in memory.steps(run["id"]) if s["key"] == "tests")
    passed, evidence, _ = registry.verify(step, {"exit_code": 0, "output": "all tests passed"})
    assert not passed
    assert evidence["signature"] == "addition-defect"


def test_impact_multihop_and_plan_cycle(memory, run):
    inspect = next(s for s in memory.steps(run["id"]) if s["key"] == "inspect")
    impact = memory.dependency_impact(inspect["id"])
    assert {r["step"]["key"] for r in impact["directly_blocked"]} == {"tests", "source"}
    evidence = next(r for r in impact["transitively_affected"] if r["step"]["key"] == "evidence")
    assert evidence["depth"] == 3
    memory.store.query("MATCH (r:AgentRun {id:$id}) SET r.status='planned'", {"id": run["id"]})
    test = next(s for s in memory.steps(run["id"]) if s["key"] == "tests")
    with pytest.raises(Conflict):
        memory.add_dependency(inspect["id"], test["id"])


def test_tenant_isolation_and_cross_session_memory(memory, run):
    other = AgentMemoryManager("isolation-" + uid())
    other.initialize()
    try:
        with pytest.raises(NotFound):
            other.get_run(run["id"])
        memory.store_fact(run["id"], "calculator", "result", "5", "test-evidence")
        assert not other.recall_facts()
        fresh = AgentMemoryManager(memory.tenant)
        assert fresh.recall_facts(query="calculator")[0]["source_reference"] == "test-evidence"
        assert fresh.events(run["id"])
    finally:
        other.store.graph.delete()


def test_complete_end_to_end_recovery(memory, run):
    w = Worker(memory)
    deadline = time.monotonic() + 30
    while memory.get_run(run["id"])["status"] == "running" and time.monotonic() < deadline:
        w.tick(run["id"])
        time.sleep(0.15)
    assert memory.get_run(run["id"])["status"] == "completed"
    steps = memory.steps(run["id"])
    assert all(s["status"] == "succeeded" for s in steps)
    tests = next(s for s in steps if s["key"] == "tests")
    assert len(memory.attempts(tests["id"])) == 2
    failures = memory.failures(tests["id"])
    assert len(failures) == 1 and failures[0]["resolved_at"] > 0
    procedures = memory.retrieve_procedures("addition-defect")
    assert procedures[0]["status"] == "verified"
    assert memory.get_related_failures(tests["id"])[0]["id"] == failures[0]["id"]
    saved = memory.save_procedure(
        failures[0]["id"],
        "Verified addition recovery",
        ["addition-fix"],
        ["rerun tests"],
        memory.attempts(tests["id"])[-1]["id"],
    )
    assert saved["status"] == "verified"
    assert memory.checkpoint(run["id"])["version"] >= 6
    graph = memory.get_execution_graph(run["id"])
    assert {"Failure", "Artifact", "Checkpoint", "Decision", "Procedure", "Fact", "Agent", "Resource"} <= {
        n["label"] for n in graph["nodes"]
    }
    assert {
        "RESOLVED_BY",
        "APPLIES_TO",
        "HAS_DECISION",
        "BASED_ON",
        "PRODUCED",
        "HANDED_OFF_TO",
        "ABOUT",
    } <= {e["label"] for e in graph["edges"]}
    decision = next(d for d in memory.decisions(run["id"]) if d["decision_type"] == "recovery")
    explanation = memory.explain_decision(decision["id"])
    assert len(explanation["sources"]) == 2
    assert all(p["relationship"] == "BASED_ON" for p in explanation["paths"])
    resource = next(n for n in graph["nodes"] if n["label"] == "Artifact")
    p = ToolRegistry(memory.tenant, run["id"]).path("dist/result.json")
    assert json.loads(p.read_text())["result"] == 5
    assert resource["properties"]["checksum"]
    before = {s["id"]: s["attempt_count"] for s in steps}
    Worker(AgentMemoryManager(memory.tenant)).tick(run["id"])
    assert before == {s["id"]: s["attempt_count"] for s in memory.steps(run["id"])}
    stale = memory.invalidate_downstream(tests["id"])
    assert {s["key"] for s in stale} == {"build", "evidence"}
    assert memory.attempts(tests["id"])[-1]["verification_result"]


def test_transitions_do_not_rerun_success():
    assert TRANSITIONS["succeeded"] == set()
    assert "succeeded" not in TRANSITIONS["running"]


def test_append_plan_and_duplicate_rejection(memory):
    run = memory.create_run("Append a validated plan")
    plan = Plan.model_validate(
        {
            "steps": [
                {
                    "key": "inspect",
                    "title": "Inspect",
                    "objective": "Inspect files",
                    "tool_name": "inspect_project",
                }
            ]
        }
    )
    memory.create_plan(run["id"], plan)
    assert len(memory.steps(run["id"])) == 1
    with pytest.raises(Conflict):
        memory.create_plan(run["id"], plan)
    spec = StepSpec(
        key="read",
        title="Read source",
        objective="Read calculator",
        tool_name="read_file",
        depends_on=["inspect"],
    )
    added = memory.add_step(run["id"], spec)
    assert added["status"] == "pending"
    additions = Plan.model_validate(
        {
            "steps": [
                {
                    "key": "extra",
                    "title": "Extra read",
                    "objective": "Inspect files",
                    "tool_name": "inspect_project",
                }
            ]
        }
    )
    assert len(memory.update_plan(run["id"], additions)) == 1
    assert len(memory.steps(run["id"])) == 3
    memory.set_run_status(run["id"], "running")
    assert [r["step"]["key"] for r in memory.get_ready_steps(run["id"])] == ["inspect", "extra"]
    with pytest.raises(Conflict):
        memory.add_step(
            run["id"], StepSpec(key="forbidden", title="Read", objective="Read", tool_name="read_file")
        )


def test_failed_verification_exhausts_budget_atomically(memory, run):
    step = first(memory, run)
    memory.store.query(
        "MATCH (s:Step {id:$id}) SET s.tool_name='run_tests',s.max_attempts=1", {"id": step["id"]}
    )
    Worker(memory).tick(run["id"])
    step = memory.get_step(step["id"])
    assert step["status"] == "failed"
    assert memory.failures(step["id"])[0]["retryable"] is False
    assert len(memory.attempts(step["id"])) == 1
    assert step["id"] not in [r["step"]["id"] for r in memory.get_ready_steps(run["id"])]


def test_blocked_steps_have_graph_evidence(memory, run):
    blocked = memory.get_blocked_steps(run["id"])
    assert {r["step"]["key"] for r in blocked} == {"tests", "build", "evidence", "source"}
    assert all(r["unsatisfied_dependencies"] for r in blocked)
