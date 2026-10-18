# Demo video script (prepared; no recording claimed)

Target length: 3–4 minutes. Record the actual browser and terminal, with readable output.

**0:00 — Problem.** “An agent loses its context when its process stops. AgentTrace keeps the goal, actions, attempts, failures, and verification in a persistent graph.” Show the overview and explicit deterministic-mode banner.

**0:20 — Graph-driven execution.** Create a run. “The planner writes a DAG into FalkorDB. The scheduler follows dependency edges, checks verified prerequisites, and atomically claims work.” Open the graph and select a step.

**0:50 — Real failure.** Open Validate calculator. Show the unittest traceback and actual failing first attempt. “This output is from a real command in an isolated sample project.”

**1:15 — Recovery changes the graph.** Show the inserted repair task and DEPENDS_ON edge. “The recovery role matches recorded failure evidence to an approved correction. A repair becomes a prerequisite, so failed tests cannot run ahead of it.”

**1:40 — Verification.** Show successful second test attempt, fresh verifier subprocess output, artifact checksum, and verified Procedure. “Success is independently checked. The original failure remains visible.”

**2:05 — Restart.** Run the process restart test or manual instructions from demo-guide.md. Show the killed worker, restarted process, interrupted attempt, and completed-step attempt_count remaining one. “A lease protects ownership; reconciliation checks uncertain local state before retry.”

**2:45 — Evidence.** Expand evidence and open the recovery decision. Highlight BASED_ON paths and dependency impact. “These explanations were recorded with the decision. This traversal finds downstream effects and work still safe independently.”

**3:15 — Why FalkorDB.** Show memory recall and tenant-isolated graph queries. “FalkorDB determines readiness, recovery prerequisites, shared context, and resume. Remove it and scheduling stops.”

**3:35 — Scope.** “The demo planner and recovery are deterministic. Optional live model planning uses a configured compatible endpoint. This submission uses local setup; AI assistance is disclosed, and participant technical review is required.”
