from app.graph.store import encode, now, uid


class RecoveryAgent:
    def __init__(self, memory):
        self.memory = memory

    def inspect(self, run_id):
        self.memory.register_agent("recovery", "recovery")
        candidates = self.memory.store.nodes(
            "MATCH (s:Step {run_id:$run}) WHERE s.status='retryable' RETURN s", {"run": run_id}
        )
        for step in candidates:
            failures = self.memory.failures(step["id"])
            if not failures:
                continue  # Interrupted local reads are handled by reconciliation, not failure recovery.
            failure = failures[-1]
            if (
                step["attempt_count"] >= step["max_attempts"]
                or failure["normalized_signature"] != "addition-defect"
            ):
                self.memory.store.query(
                    "MATCH (s:Step {id:$id}) WHERE s.status='retryable' SET s.status='failed'",
                    {"id": step["id"]},
                )
                self.memory.record_execution_event(
                    run_id,
                    "recovery_blocked",
                    "No approved correction or retry budget exhausted",
                    step["id"],
                    actor="recovery",
                )
                continue
            # The write is conditional, so multiple recovery workers cannot insert duplicate remedies.
            known = self.memory.retrieve_procedures("addition-defect")
            verified = next((p for p in known if p["status"] == "verified"), None)
            procedure_id = verified["id"] if verified else uid()
            repair_id, ts = uid(), now()
            repair = dict(
                id=repair_id,
                run_id=run_id,
                key="repair_" + step["key"],
                title="Repair addition defect",
                objective="Apply approved correction: addition replaces subtraction",
                status="pending",
                priority=100,
                tool_name="apply_approved_patch",
                input_json=encode({"patch": "addition-fix"}),
                expected_output="return a + b",
                success_criteria_json=encode({"contains": "return a + b"}),
                attempt_count=0,
                max_attempts=2,
                retry_after_ms=0,
                lease_owner="",
                lease_until_ms=0,
                verification_status="unverified",
                current_attempt_id="",
                created_at=ts,
                updated_at=ts,
                plan_version=2,
                output_summary="",
                error_summary="",
            )
            rows = self.memory.store.query(
                """
                MATCH (r:AgentRun {id:$run})-[:HAS_STEP]->(s:Step {id:$step})
                MATCH (s)-[:HAS_ATTEMPT]->(:Attempt)-[:CAUSED_FAILURE]->(f:Failure {id:$failure})
                WHERE s.status='retryable' AND NOT (s)-[:RECOVERY_PLANNED]->(f)
                CREATE (s)-[:RECOVERY_PLANNED]->(f)
                CREATE (r)-[:HAS_STEP]->(repair:Step) SET repair=$repair
                CREATE (s)-[:DEPENDS_ON]->(repair)
                SET r.plan_version=r.plan_version+1
                MERGE (p:Procedure {id:$procedure})
                ON CREATE SET p.name='Correct calculator addition',p.problem_signature='addition-defect',
                    p.instructions_json=$instructions,p.preconditions_json=$preconditions,
                    p.verification_json=$verification,p.status='proposed',p.confidence=0.5,
                    p.verified_success_count=0,p.verified_failure_count=0,p.last_verified_at=0
                MERGE (p)-[:APPLIES_TO]->(f)
                CREATE (repair)-[:USES_PROCEDURE]->(p)
                CREATE (s)-[:HAS_DECISION]->(d:Decision {id:$decision,run_id:r.id,action:'apply approved patch',
                    decision_type:'recovery',actor_id:'recovery',selected_option:p.id,created_at:$now,
                    rationale_summary:$rationale,evidence_status:'proposed',query_trace:'Failure signature → Procedure → repair dependency'})
                CREATE (d)-[:BASED_ON]->(f) CREATE (d)-[:BASED_ON]->(p)
                RETURN repair
                """,
                {
                    "run": run_id,
                    "step": step["id"],
                    "failure": failure["id"],
                    "repair": repair,
                    "procedure": procedure_id,
                    "instructions": encode(["Apply pre-approved addition-fix"]),
                    "preconditions": encode(["Real AssertionError", "Source contains return a - b"]),
                    "verification": encode(["Independently rerun all calculator tests"]),
                    "decision": uid(),
                    "now": ts,
                    "rationale": "Verified procedure retrieved from shared graph"
                    if verified
                    else "Observed test failure and exact source precondition match the approved repair",
                },
            )
            if rows:
                self.memory.record_execution_event(
                    run_id,
                    "recovery_selected",
                    "Graph failure evidence created a repair prerequisite",
                    step["id"],
                    actor="recovery",
                    payload={
                        "failure_id": failure["id"],
                        "procedure_id": procedure_id,
                        "repair_step_id": repair_id,
                    },
                )
                self.memory.record_execution_event(
                    run_id,
                    "retry_scheduled",
                    "Failed tests wait for repair and exponential backoff",
                    step["id"],
                    actor="recovery",
                )
