import json
import platform
import statistics
import time
from pathlib import Path
from app.memory.manager import AgentMemoryManager, ELIGIBLE
from app.agents.planner import PlannerAgent
from app.workers.runner import Worker

m = AgentMemoryManager("benchmark")
m.initialize()
r = m.create_run("Measure representative graph traversals")
PlannerAgent(m).plan(r)
m.set_run_status(r["id"], "running")
Worker(m, "benchmark-executor").tick(r["id"])
step = m.steps(r["id"])[0]
queries = {
    "run_lookup": ("MATCH (r:AgentRun {id:$id}) RETURN r", {"id": r["id"]}),
    "step_lookup": ("MATCH (s:Step {id:$id}) RETURN s", {"id": step["id"]}),
    "dependency_traversal": (
        "MATCH p=(s:Step)-[:DEPENDS_ON*1..30]->(:Step {id:$id}) RETURN nodes(p)",
        {"id": step["id"]},
    ),
    "ready_steps": (
        ELIGIBLE + " RETURN s,deps ORDER BY s.priority DESC,s.created_at LIMIT 30",
        {"run": r["id"], "now": int(time.time() * 1000)},
    ),
    "attempt_history": (
        "MATCH (:Step {id:$id})-[:HAS_ATTEMPT]->(a:Attempt) RETURN a ORDER BY a.sequence",
        {"id": step["id"]},
    ),
    "recent_events": (
        "MATCH (e:Event {run_id:$id}) RETURN e ORDER BY e.occurred_at DESC LIMIT 20",
        {"id": r["id"]},
    ),
    "latest_checkpoint": (
        "MATCH (:AgentRun {id:$id})-[:HAS_CHECKPOINT]->(c:Checkpoint) RETURN c ORDER BY c.version DESC LIMIT 1",
        {"id": r["id"]},
    ),
}
result = {
    "environment": {
        "os": platform.platform(),
        "python": platform.python_version(),
        "database_image": "falkordb/falkordb@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a",
        "steps": 5,
        "iterations": 50,
        "measurement": "Client wall-clock including round trip; small synthetic graph, not a scale benchmark",
    },
    "queries": {},
}
for name, (query, params) in queries.items():
    timings = []
    for _ in range(50):
        started = time.perf_counter()
        m.store.query(query, params, read=True)
        timings.append((time.perf_counter() - started) * 1000)
    plan = str(m.store.graph.explain(query, params))
    result["queries"][name] = {
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(sorted(timings)[47], 3),
        "explain": plan,
    }
target = Path(__file__).resolve().parents[1] / "docs" / "query-timings.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
m.store.graph.delete()
