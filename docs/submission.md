# AgentTrace submission draft

**AI Agents That Remember, Recover, and Explain Every Action.**

Primary track: **Agent Memory and Coordination**.

Secondary track: **Agents That Act on Connected Data** — actual dependency, failure, and procedure relationships determine execution and recovery actions; multi-hop impact traversal explains affected tasks.

AgentTrace is a local graph-native agent execution system. A goal becomes a validated task DAG in FalkorDB. Workers claim eligible tasks with leases, execute constrained tools, independently verify results, preserve failures, and select an approved correction using stored evidence. Checkpoints and reconciliation let a restarted process continue unfinished work while retaining completed actions. A live dashboard exposes the graph, activity, memory, attempts, and decision evidence.

## Technical highlights

- FalkorDB is the only task/memory database; availability failure stops scheduling.
- Conditional claims and fencing tokens prevent duplicate ownership and stale finalization.
- Real broken application, real unittest failure, exact approved repair, independent verification.
- Failure → Procedure evidence creates a new scheduling dependency.
- Tenant-specific graphs selected from authenticated server mappings.
- Real worker kill/restart integration test; persistent-volume database restart test.
- React Flow graph and authenticated SSE backed by persisted Event records.
- Dependency impact paths and downstream stale-verification marking.

## Links

- Repository URL: **not published yet**.
- Live deployment: **not deployed publicly**; complete local setup is in README.
- Demo video: **not recorded yet**; script prepared in video-script.md.

## Submission checklist

- [x] Source implementation and local setup instructions.
- [x] Graph schema, key Cypher queries, architecture, demo instructions.
- [x] AI assistance disclosure.
- [ ] Public repository URL supplied by participant.
- [ ] Actual video recorded and URL supplied.
- [ ] Participant reviews code, validates behavior, understands and explains graph queries and design choices.
- [ ] Participant confirms registration, team eligibility, development-window compliance, and submits before the official deadline.

Development timestamps and Git history are actual local history; no dates are backdated. The project does not claim human review, registration, acceptance, or eligibility merely because code exists. The organizer's [rules](https://www.wemakedevs.org/hackathons/falkordb/rules) require meaningful participant contribution and technical understanding and allow AI assistance with disclosure.

## Limits to disclose

The working demo is fixed to a controlled calculator application; recovery supports one approved correction. Live planning requires a configured model and is not verified here. The tool allowlist is not an OS sandbox for arbitrary hostile repositories. Retrieval is bounded relationship-aware filtering with transparent ordering, not embedding-based semantic reasoning. RDB persistence protects saved checkpoints; abrupt database/host failure can lose more recent writes. AOF was disabled after a reproduced replay crash. Backups and production scale/security require further operational work. Stale verification is flagged; automatic revalidation workflows are not implemented. See README and recovery-design.md for detail.
