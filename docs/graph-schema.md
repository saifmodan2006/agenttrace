# Graph schema

Properties are scalar values or scalar arrays. Rich structures are serialized as `*_json` strings. IDs are UUIDs, timestamps are UTC epoch milliseconds, and display formatting uses the viewer's locale.

| Label | Responsibility and principal properties |
|---|---|
| AgentRun | tenant_id, goal, description, status, mode, plan_version, checkpoint_version, created_at, updated_at, completed_at, summary |
| Step | run_id, key, title, objective, status, priority, tool_name, input_json, success_criteria_json, attempt_count, max_attempts, retry_after_ms, verification_status, lease_owner, lease_until_ms, current_attempt_id |
| Attempt | step_id, run_id, sequence, agent_id, tool_name, input_hash, idempotency_key, status, lease_token, timestamps, exit_code, output_summary, error_summary, verification_result |
| Agent | name, role, status, capabilities_json, current_step_id, last_heartbeat_at |
| Event | immutable occurrence: run_id, step_id, attempt_id, actor_id, event_type, occurred_at, summary, payload_reference |
| Failure | run_id, category, normalized_signature, error_code, description, root_cause, retryable, discovered_at, resolved_at |
| Procedure | name, problem_signature, instructions_json, preconditions_json, verification_json, status, confidence, verified_success_count, verified_failure_count, last_verified_at |
| Fact | run_id, subject, predicate, value, confidence, source_reference, learned_at, valid_until, status |
| Artifact | run_id, type, filename, storage_reference, checksum, mime_type, size, created_at |
| Decision | run_id, action, decision_type, selected_option, rationale_summary, evidence_status, actor_id, created_at, query_trace; scheduling dependency IDs snapshot |
| Checkpoint | run_id, version, summary, current_goal, state_json, created_at |
| Resource | type, name, reference, available, metadata_json |

All labels have range indexes and unique constraints on `id`. Step additionally indexes `run_id` and `status`; Attempt indexes `step_id`; Event, Failure, and Checkpoint index `run_id`. Initialization is idempotent and tested against the pinned image (module version 4.22.1). Unique constraints use `GRAPH.CONSTRAINT CREATE <graph> UNIQUE NODE <Label> PROPERTIES 1 id`. Not every optional property in the original product specification is populated; the table describes the implemented fields. Constraint creation errors other than an existing constraint fail startup.

## Relationships

| Source → relationship → target | Evidence |
|---|---|
| AgentRun → HAS_STEP → Step | Validated planner DAG or recorded recovery |
| Step → DEPENDS_ON → Step | Explicit plan dependency / recovery prerequisite |
| Step → HAS_ATTEMPT → Attempt | Atomic execution claim |
| Attempt → CAUSED_FAILURE → Failure | Actual failed verification |
| Failure → RESOLVED_BY → Procedure | A later independent verification passed |
| Step → ASSIGNED_TO → Agent | Successful conditional claim |
| Step → PRODUCED → Artifact | Verified build artifact |
| AgentRun → HAS_CHECKPOINT → Checkpoint | Persisted execution snapshot |
| AgentRun → RECORDED_EVENT → Event | Actual recorded occurrence |
| Step → HAS_DECISION → Decision | Scheduling, recovery, or verification choice |
| Decision → BASED_ON → Event / Fact | Supported by generic evidence retrieval; event edges are produced by current demo decisions, Fact edges are reserved for future fact-based decisions |
| Decision → BASED_ON → Step / Attempt / Failure / Procedure | Actual prerequisites, verification attempts, or recovery evidence |
| Procedure → APPLIES_TO → Failure | Signature and observed precondition match |
| Step → TARGETS → Resource | Planned isolated project |
| Agent → HANDED_OFF_TO → Agent | Context JSON, run step, attempts, expected output, pending action, evidence references, timestamp |
| Fact → ABOUT → Resource | Verified build fact about the project |
| AgentRun → LEARNED → Fact | Fact provenance |
| Step → RECOVERY_PLANNED → Failure | Prevent duplicate recovery insertion |
| Step → USES_PROCEDURE → Procedure | Selected approved correction |
| Procedure → VERIFIED_BY → Attempt | Explicitly saved procedure with successful verification evidence |

Edges are directed. **A dependent step points to its prerequisite.** Readiness traverses outwards from a step; impact traverses inwards toward dependent steps. Transitive traversal is bounded at 30 hops, and graph export is bounded. The UI expands evidence records explicitly.

State transitions are defined in `app/models/schemas.py`. Core path: pending → (derived ready eligibility) → running → verifying → succeeded / retryable / failed. A lease expiration moves running/verifying to needs_reconciliation, then to succeeded/retryable/failed after inspection. Pending and retryable are claimable only when the full readiness predicate passes. `blocked` and `ready` are accepted controlled states; normal waiting dependencies are derived by graph traversal without mutating the pending state during reads. Completed attempts and verification evidence are preserved when downstream verification becomes stale.
