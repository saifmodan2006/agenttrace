import time
from app.memory.manager import AgentMemoryManager
from app.agents.planner import PlannerAgent
from app.workers.runner import Worker

m = AgentMemoryManager("vertical-slice")
m.initialize()
r = m.create_run("Repair and validate the broken calculator")
PlannerAgent(m).plan(r)
m.set_run_status(r["id"], "running")
w = Worker(m)
for _ in range(40):
    w.tick(r["id"])
    print([(s["key"], s["status"]) for s in m.steps(r["id"])], flush=True)
    if m.get_run(r["id"])["status"] in {"completed", "failed"}:
        break
    time.sleep(0.25)
print(m.get_run(r["id"]))
print("Graph nodes:", len(m.get_execution_graph(r["id"])["nodes"]))
assert m.get_run(r["id"])["status"] == "completed"
