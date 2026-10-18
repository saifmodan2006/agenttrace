"""Authoritative graph memory. Every mutation uses a parameterized Cypher write.

Conditional claims and finalizations are single GRAPH.QUERY commands, serialized
by FalkorDB's graph write lock. No process-local lock or shadow task store exists.
"""

import hashlib
from app.graph.store import GraphStore, encode, now, properties, uid
from app.models.schemas import Plan, StepSpec, TRANSITIONS, TOOLS

ELIGIBLE = """
MATCH (r:AgentRun {id:$run})-[:HAS_STEP]->(s:Step)
OPTIONAL MATCH (s)-[:DEPENDS_ON]->(d:Step)
WITH r,s,collect(d) AS deps
WHERE r.status = 'running' AND s.status IN ['pending','ready','retryable']
AND s.retry_after_ms <= $now AND s.attempt_count < s.max_attempts
AND s.lease_until_ms <= $now
AND all(d IN deps WHERE d.status = 'succeeded' AND d.verification_status = 'passed')
"""


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


class AgentMemoryManager:
    def __init__(self, tenant="demo"):
        self.store = GraphStore(tenant)
        self.tenant = tenant

    def initialize(self):
        self.store.initialize()

    def create_run(self, goal, description="", mode="demo"):
        run = dict(
            id=uid(),
            tenant_id=self.tenant,
            goal=goal,
            description=description,
            status="planned",
            created_at=now(),
            updated_at=now(),
            plan_version=1,
            checkpoint_version=0,
            summary="",
            mode=mode,
            metadata_json=encode({"scenario": "broken-app"}),
        )
        self.store.query("CREATE (r:AgentRun) SET r=$props", {"props": run})
        self.record_execution_event(run["id"], "run_created", goal, actor="planner")
        return run

    def get_run(self, run_id):
        rows = self.store.nodes("MATCH (r:AgentRun {id:$id}) RETURN r", {"id": run_id})
        if not rows:
            raise NotFound("Run not found in this tenant")
        return rows[0]

    def list_runs(self, limit=50, offset=0):
        return self.store.nodes(
            "MATCH (r:AgentRun) RETURN r ORDER BY r.created_at DESC SKIP $offset LIMIT $limit",
            {"limit": limit, "offset": offset},
        )

    def get_step(self, step_id):
        rows = self.store.nodes("MATCH (s:Step {id:$id}) RETURN s", {"id": step_id})
        if not rows:
            raise NotFound("Step not found in this tenant")
        return rows[0]

    def steps(self, run_id):
        self.get_run(run_id)
        return self.store.nodes(
            "MATCH (:AgentRun {id:$run})-[:HAS_STEP]->(s:Step) RETURN s ORDER BY s.created_at,s.id",
            {"run": run_id},
        )

    def create_plan(self, run_id, plan: Plan):
        # Pydantic already validates the DAG and tools. Entire plan is one write.
        run = self.get_run(run_id)
        if run["status"] != "planned":
            raise Conflict("Only a planned run can receive its initial plan")
        mapping = {s.key: uid() for s in plan.steps}
        ts = now()
        rows, edges = [], []
        for i, s in enumerate(plan.steps):
            props = dict(
                id=mapping[s.key],
                run_id=run_id,
                key=s.key,
                title=s.title,
                objective=s.objective,
                status="pending",
                priority=s.priority,
                tool_name=s.tool_name,
                input_json=encode(s.input),
                expected_output=s.objective,
                success_criteria_json=encode(s.success_criteria),
                preconditions_json="[]",
                retry_policy_json=encode({"backoff_ms": 1000}),
                attempt_count=0,
                max_attempts=s.max_attempts,
                retry_after_ms=0,
                verification_status="unverified",
                lease_owner="",
                lease_until_ms=0,
                current_attempt_id="",
                plan_version=1,
                created_at=ts + i,
                updated_at=ts,
                output_summary="",
                error_summary="",
            )
            rows.append(props)
            edges.extend({"source": mapping[s.key], "target": mapping[d]} for d in s.depends_on)
        written = self.store.query(
            """
            MATCH (r:AgentRun {id:$run}) WHERE r.status='planned' AND NOT (r)-[:HAS_STEP]->()
            UNWIND $steps AS props CREATE (s:Step) SET s=props CREATE (r)-[:HAS_STEP]->(s)
            WITH r,collect(s) AS created
            FOREACH (e IN $edges |
                FOREACH (a IN [n IN created WHERE n.id=e.source] |
                    FOREACH (b IN [n IN created WHERE n.id=e.target] | CREATE (a)-[:DEPENDS_ON]->(b))))
            RETURN r.id
            """,
            {"run": run_id, "steps": rows, "edges": edges},
        )
        if not written:
            raise Conflict("Run already has a plan")
        self.record_execution_event(
            run_id, "step_planned", f"Validated DAG: {len(rows)} steps", actor="planner"
        )
        resource = {
            "id": uid(),
            "type": "workspace",
            "name": "Isolated broken application",
            "reference": f"workspace://{run_id}",
            "available": True,
            "metadata_json": "{}",
        }
        self.store.query(
            "MATCH (s:Step {run_id:$run}) MERGE (r:Resource {id:$id}) SET r=$props MERGE (s)-[:TARGETS]->(r)",
            {"run": run_id, "id": resource["id"], "props": resource},
        )
        return self.steps(run_id)

    def add_step(self, run_id, spec: StepSpec):
        if spec.tool_name not in TOOLS:
            raise Conflict("Unregistered tool")
        existing = self.steps(run_id)
        keys = {s["key"]: s["id"] for s in existing}
        if spec.key in keys or any(key not in keys for key in spec.depends_on):
            raise Conflict("Duplicate key or unknown dependency")
        if len(existing) >= 30:
            raise Conflict("Plan step limit exceeded")
        ts = now()
        props = dict(
            id=uid(),
            run_id=run_id,
            key=spec.key,
            title=spec.title,
            objective=spec.objective,
            expected_output=spec.objective,
            status="pending",
            priority=spec.priority,
            tool_name=spec.tool_name,
            input_json=encode(spec.input),
            success_criteria_json=encode(spec.success_criteria),
            attempt_count=0,
            max_attempts=spec.max_attempts,
            retry_after_ms=0,
            lease_owner="",
            lease_until_ms=0,
            verification_status="unverified",
            current_attempt_id="",
            created_at=ts,
            updated_at=ts,
            output_summary="",
            error_summary="",
            plan_version=self.get_run(run_id)["plan_version"] + 1,
        )
        rows = self.store.query(
            """
            MATCH (r:AgentRun {id:$run}) WHERE r.status='planned'
            OPTIONAL MATCH (r)-[:HAS_STEP]->(old:Step)
            WITH r,collect(old) AS existing
            WHERE size(existing)<30 AND all(s IN existing WHERE s.key<>$key)
            CREATE (r)-[:HAS_STEP]->(s:Step) SET s=$props,r.plan_version=r.plan_version+1
            FOREACH (d IN [n IN existing WHERE n.id IN $deps] | CREATE (s)-[:DEPENDS_ON]->(d))
            RETURN s
            """,
            {"run": run_id, "key": spec.key, "props": props, "deps": [keys[k] for k in spec.depends_on]},
        )
        if not rows:
            raise Conflict("Plan already executing or step conflicts")
        self.record_execution_event(run_id, "step_planned", spec.title, props["id"], actor="planner")
        return properties(rows[0][0])

    def update_plan(self, run_id, additions: Plan):
        """Append a validated DAG to a not-yet-started plan; historical steps are never deleted."""
        self.get_run(run_id)
        added = []
        pending = {s.key: s for s in additions.steps}
        while pending:
            for key, spec in list(pending.items()):
                if not any(d in pending for d in spec.depends_on):
                    added.append(self.add_step(run_id, spec))
                    del pending[key]
        return added

    def start_attempt(self, run_id, step_id, owner, lease_ms=15000):
        # Claim and attempt creation are intentionally inseparable.
        return self.claim_step(run_id, step_id, owner, lease_ms)

    def get_related_failures(self, step_id):
        self.get_step(step_id)
        return self.store.nodes(
            "MATCH (:Step {id:$id})-[:HAS_ATTEMPT]->(:Attempt)-[:CAUSED_FAILURE]->(f:Failure) "
            "MATCH (related:Failure) WHERE related.normalized_signature=f.normalized_signature "
            "RETURN DISTINCT related ORDER BY related.discovered_at DESC LIMIT 20",
            {"id": step_id},
        )

    def save_procedure(self, failure_id, name, instructions, verification, evidence_attempt_id):
        # An arbitrary client cannot promote an unverified recovery to authoritative memory.
        props = dict(
            id=uid(),
            name=name,
            instructions_json=encode(instructions),
            verification_json=encode(verification),
            preconditions_json="[]",
            status="verified",
            confidence=1.0,
            verified_success_count=1,
            verified_failure_count=0,
            last_verified_at=now(),
        )
        rows = self.store.query(
            """
            MATCH (s:Step)-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt})
            MATCH (s)-[:HAS_ATTEMPT]->(:Attempt)-[:CAUSED_FAILURE]->(f:Failure {id:$failure})
            WHERE a.status='succeeded' AND s.verification_status='passed' AND f.run_id=s.run_id
            CREATE (p:Procedure) SET p=$props,p.problem_signature=f.normalized_signature
            CREATE (p)-[:APPLIES_TO]->(f) CREATE (p)-[:VERIFIED_BY]->(a) RETURN p
            """,
            {"attempt": evidence_attempt_id, "failure": failure_id, "props": props},
        )
        if not rows:
            raise Conflict("Verified evidence from the same run is required")
        return properties(rows[0][0])

    def add_dependency(self, step_id, dependency_id):
        a, b = self.get_step(step_id), self.get_step(dependency_id)
        if a["run_id"] != b["run_id"]:
            raise Conflict("Cross-run dependencies are forbidden")
        # Reject graph changes once any attempt has begun. This makes the
        # cycle check + insertion safe against executing workers.
        result = self.store.query(
            """
            MATCH (r:AgentRun {id:$run})-[:HAS_STEP]->(a:Step {id:$a}), (b:Step {id:$b})
            WHERE r.status='planned' AND a.id<>b.id AND NOT (b)-[:DEPENDS_ON*1..30]->(a)
            MERGE (a)-[:DEPENDS_ON]->(b) RETURN a
            """,
            {"run": a["run_id"], "a": step_id, "b": dependency_id},
        )
        if not result:
            raise Conflict("Cycle or plan already executing")

    def set_run_status(self, run_id, status):
        allowed = {
            "running": ["planned", "paused", "interrupted", "running"],
            "paused": ["running", "paused"],
        }
        if status not in allowed:
            raise Conflict("Unsupported run transition")
        result = self.store.query(
            "MATCH (r:AgentRun {id:$id}) WHERE r.status IN $allowed "
            "SET r.status=$status,r.updated_at=$now RETURN r",
            {"id": run_id, "allowed": allowed[status], "status": status, "now": now()},
        )
        if not result:
            raise Conflict("Run cannot enter this state")
        self.record_execution_event(run_id, "run_" + status, f"Run {status}")
        return properties(result[0][0])

    def get_ready_steps(self, run_id):
        self.get_run(run_id)
        rows = self.store.query(
            ELIGIBLE
            + """
            OPTIONAL MATCH (s)-[:TARGETS]->(resource:Resource)
            WITH s,deps,collect(resource) AS resources
            WHERE all(resource IN resources WHERE resource.available=true)
            RETURN s,deps ORDER BY s.priority DESC,s.created_at LIMIT 30
            """,
            {"run": run_id, "now": now()},
            read=True,
        )
        return [dict(step=properties(row[0]), dependencies=[properties(d) for d in row[1]]) for row in rows]

    def get_blocked_steps(self, run_id):
        self.get_run(run_id)
        rows = self.store.query(
            """
            MATCH (:AgentRun {id:$run})-[:HAS_STEP]->(s:Step)-[:DEPENDS_ON]->(d:Step)
            WHERE s.status IN ['pending','ready','retryable','blocked']
            AND (d.status<>'succeeded' OR d.verification_status<>'passed')
            RETURN s,collect(d)
            """,
            {"run": run_id},
            read=True,
        )
        return [
            {
                "step": properties(row[0]),
                "unsatisfied_dependencies": [properties(d) for d in row[1]],
                "reason": "Required dependency has no current passed verification",
            }
            for row in rows
        ]

    def register_agent(self, agent_id, role="executor"):
        self.store.query(
            "MERGE (a:Agent {id:$id}) SET a.name=$id,a.role=$role,a.status='idle',"
            "a.last_heartbeat_at=$now,a.capabilities_json=$caps",
            {"id": agent_id, "role": role, "now": now(), "caps": encode([role])},
        )

    def heartbeat(self, agent_id):
        self.store.query(
            "MATCH (a:Agent {id:$id}) SET a.last_heartbeat_at=$now", {"id": agent_id, "now": now()}
        )

    def claim_step(self, run_id, step_id, owner, lease_ms=15000):
        attempt_id, token, event_id, decision_id, ts = uid(), uid(), uid(), uid(), now()
        rows = self.store.query(
            ELIGIBLE
            + """
            AND s.id=$step
            OPTIONAL MATCH (s)-[:TARGETS]->(resource:Resource)
            WITH r,s,deps,collect(resource) AS resources
            WHERE all(resource IN resources WHERE resource.available=true)
            MATCH (agent:Agent {id:$owner})
            SET s.status='running',s.lease_owner=$owner,s.lease_until_ms=$until,
                s.current_attempt_id=$attempt,s.attempt_count=s.attempt_count+1,s.updated_at=$now,
                s.started_at=$now,agent.status='busy',agent.current_step_id=s.id,agent.last_heartbeat_at=$now
            CREATE (s)-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt,step_id:s.id,run_id:r.id,
                sequence:s.attempt_count,agent_id:$owner,tool_name:s.tool_name,input_json:s.input_json,
                input_hash:$hash,idempotency_key:$attempt,status:'running',started_at:$now,lease_token:$token})
            MERGE (s)-[:ASSIGNED_TO]->(agent)
            CREATE (r)-[:RECORDED_EVENT]->(e:Event {id:$event,event_type:'task_claimed',
                run_id:r.id,step_id:s.id,attempt_id:$attempt,actor_id:$owner,occurred_at:$now,
                summary:'Atomic claim: dependencies verified, retry budget and resources available',
                dependency_ids:[dep IN deps | dep.id],dependency_status_at_claim:'succeeded / passed'})
            CREATE (s)-[:HAS_DECISION]->(d:Decision {id:$decision,run_id:r.id,
                action:'execute',decision_type:'scheduling',selected_option:s.id,actor_id:$owner,
                created_at:$now,rationale_summary:'All dependency checks passed in the atomic claim query',
                query_trace:'ELIGIBLE + conditional claim',evidence_status:'verified_from_graph',
                dependency_ids_at_claim:[dep IN deps | dep.id]})
            CREATE (d)-[:BASED_ON]->(e)
            FOREACH (dep IN deps | CREATE (d)-[:BASED_ON]->(dep))
            RETURN s,a
            """,
            {
                "run": run_id,
                "step": step_id,
                "owner": owner,
                "now": ts,
                "until": ts + lease_ms,
                "attempt": attempt_id,
                "token": token,
                "event": event_id,
                "decision": decision_id,
                "hash": hashlib.sha256(self.get_step(step_id)["input_json"].encode()).hexdigest(),
            },
        )
        return {"step": properties(rows[0][0]), "attempt": properties(rows[0][1])} if rows else None

    def renew_lease(self, step_id, attempt_id, owner, token, lease_ms=15000):
        rows = self.store.query(
            """
            MATCH (s:Step {id:$id})-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt})
            WHERE s.current_attempt_id=a.id AND s.lease_owner=$owner AND a.lease_token=$token
            AND s.status IN ['running','verifying'] AND s.lease_until_ms>$now
            SET s.lease_until_ms=$until RETURN s.id
            """,
            {
                "id": step_id,
                "attempt": attempt_id,
                "owner": owner,
                "token": token,
                "now": now(),
                "until": now() + lease_ms,
            },
        )
        if not rows:
            raise Conflict("Expired or stale lease")
        self.heartbeat(owner)
        return True

    def transition(self, step_id, target, owner, token, attempt_id, extra=None):
        sources = [source for source, targets in TRANSITIONS.items() if target in targets]
        rows = self.store.query(
            """
            MATCH (s:Step {id:$step})-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt})
            WHERE s.status IN $sources AND s.current_attempt_id=a.id AND a.lease_token=$token
            AND s.lease_owner=$owner AND s.lease_until_ms>$now
            SET s.status=$target,s.updated_at=$now,s += $extra RETURN s
            """,
            {
                "step": step_id,
                "attempt": attempt_id,
                "sources": sources,
                "target": target,
                "owner": owner,
                "token": token,
                "now": now(),
                "extra": extra or {},
            },
        )
        if not rows:
            raise Conflict("Invalid transition or stale lease")
        return properties(rows[0][0])

    def record_execution_event(
        self, run_id, event_type, summary, step_id="", attempt_id="", actor="system", payload=None
    ):
        event = dict(
            id=uid(),
            event_type=event_type,
            run_id=run_id,
            step_id=step_id,
            attempt_id=attempt_id,
            actor_id=actor,
            occurred_at=now(),
            summary=summary,
            payload_reference=encode(payload or {}),
        )
        self.store.query(
            "MATCH (r:AgentRun {id:$run}) CREATE (r)-[:RECORDED_EVENT]->(e:Event) SET e=$props",
            {"run": run_id, "props": event},
        )
        return event

    def record_attempt_result(self, step_id, attempt_id, owner, token, result):
        ts = now()
        rows = self.store.query(
            """
            MATCH (s:Step {id:$step})-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt})
            WHERE s.status='running' AND a.status='running' AND s.current_attempt_id=a.id
            AND s.lease_owner=$owner AND a.lease_token=$token AND s.lease_until_ms>$now
            SET s.status='verifying',s.output_summary=$output,s.updated_at=$now,
                a.status='verifying',a.finished_at=$now,a.duration_ms=$now-a.started_at,
                a.exit_code=$code,a.output_summary=$output,a.error_summary=$error
            RETURN s
            """,
            {
                "step": step_id,
                "attempt": attempt_id,
                "owner": owner,
                "token": token,
                "now": ts,
                "output": result["output"][:16000],
                "code": result["exit_code"],
                "error": result.get("error", "")[:16000],
            },
        )
        if not rows:
            raise Conflict("Duplicate result or stale lease")
        s = properties(rows[0][0])
        self.record_execution_event(
            s["run_id"],
            "tool_completed",
            f"Tool exit code: {result['exit_code']}",
            step_id,
            attempt_id,
            owner,
            result,
        )
        return s

    def verify_step(self, step_id, attempt_id, owner, token, passed, evidence, artifact=None):
        """Verification evidence must originate from the trusted worker, never public API input."""
        ts = now()
        current = self.get_step(step_id)
        exhausted = current["attempt_count"] >= current["max_attempts"]
        failure = dict(
            id=uid(),
            run_id=current["run_id"],
            category="verification",
            error_code=evidence.get("signature", "unknown"),
            normalized_signature=evidence.get("signature", "unknown"),
            description=evidence["summary"],
            root_cause=evidence.get("root_cause", "Unclassified; requires inspection"),
            severity="error",
            retryable=evidence.get("signature") == "addition-defect" and not exhausted,
            discovered_at=ts,
            resolved_at=0,
        )
        rows = self.store.query(
            """
            MATCH (r:AgentRun)-[:HAS_STEP]->(s:Step {id:$step})-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt})
            WHERE s.status='verifying' AND a.status='verifying' AND s.current_attempt_id=a.id
            AND s.lease_owner=$owner AND a.lease_token=$token AND s.lease_until_ms>$now
            SET s.status=$status,s.verification_status=$verification,s.updated_at=$now,
                s.completed_at=$completed,s.lease_until_ms=0,s.error_summary=$error,
                s.retry_after_ms=$retry,
                a.status=$status,a.verification_result=$evidence
            FOREACH (props IN $failures | CREATE (a)-[:CAUSED_FAILURE]->(f:Failure) SET f=props)
            FOREACH (props IN $artifacts | CREATE (s)-[:PRODUCED]->(artifact:Artifact) SET artifact=props)
            CREATE (r)-[:RECORDED_EVENT]->(e:Event {id:$event,run_id:r.id,step_id:s.id,
                attempt_id:a.id,event_type:$type,actor_id:'verifier',occurred_at:$now,summary:$summary,
                payload_reference:$evidence})
            CREATE (s)-[:HAS_DECISION]->(d:Decision {id:$decision,run_id:r.id,action:$status,
                decision_type:'verification',actor_id:'verifier',created_at:$now,
                rationale_summary:$summary,evidence_status:'verified_from_graph',query_trace:'independent tool verification'})
            CREATE (d)-[:BASED_ON]->(e) CREATE (d)-[:BASED_ON]->(a)
            RETURN s
            """,
            {
                "step": step_id,
                "attempt": attempt_id,
                "owner": owner,
                "token": token,
                "now": ts,
                "status": "succeeded" if passed else ("failed" if exhausted else "retryable"),
                "verification": "passed" if passed else "failed",
                "completed": ts if passed else 0,
                "evidence": encode(evidence),
                "event": uid(),
                "decision": uid(),
                "type": "verification_passed" if passed else "failure_detected",
                "summary": evidence["summary"],
                "error": "" if passed else evidence["summary"],
                "retry": 0 if passed else ts + 1000 * 2 ** min(current["attempt_count"] - 1, 5),
                "failures": [] if passed else [failure],
                "artifacts": [artifact] if artifact and passed else [],
            },
        )
        if not rows:
            raise Conflict("Duplicate verification or stale lease")
        step = properties(rows[0][0])
        if passed:
            # Resolve only failures whose recovery is confirmed by this verified step.
            self.store.query(
                """
                MATCH (s:Step {id:$step})-[:HAS_ATTEMPT]->(:Attempt)-[:CAUSED_FAILURE]->(f:Failure)
                MATCH (p:Procedure)-[:APPLIES_TO]->(f)
                WHERE f.resolved_at=0
                SET f.resolved_at=$now,p.status='verified',p.confidence=1.0,
                    p.verified_success_count=p.verified_success_count+1,p.last_verified_at=$now
                MERGE (f)-[:RESOLVED_BY]->(p)
                """,
                {"step": step_id, "now": ts},
            )
        self.store.query(
            "MATCH (a:Agent {id:$owner}) SET a.status='idle',a.current_step_id=''", {"owner": owner}
        )
        return step

    def record_failure(self, step_id, attempt_id, evidence):
        step = self.get_step(step_id)
        signature = evidence.get("signature", "unknown")
        failure = dict(
            id=uid(),
            run_id=step["run_id"],
            category="verification",
            error_code=signature,
            normalized_signature=signature,
            description=evidence["summary"],
            root_cause=evidence.get("root_cause", "Unclassified; requires inspection"),
            severity="error",
            retryable=signature == "addition-defect",
            discovered_at=now(),
            resolved_at=0,
        )
        self.store.query(
            "MATCH (a:Attempt {id:$attempt}), (s:Step {id:$step}) "
            "CREATE (a)-[:CAUSED_FAILURE]->(f:Failure) SET f=$props "
            "SET s.retry_after_ms=$retry",
            {
                "step": step_id,
                "attempt": attempt_id,
                "props": failure,
                "retry": now() + 1000 * 2 ** min(step["attempt_count"] - 1, 5),
            },
        )
        return failure

    def attempts(self, step_id):
        self.get_step(step_id)
        return self.store.nodes(
            "MATCH (:Step {id:$id})-[:HAS_ATTEMPT]->(a:Attempt) RETURN a ORDER BY a.sequence", {"id": step_id}
        )

    def failures(self, step_id):
        self.get_step(step_id)
        return self.store.nodes(
            "MATCH (:Step {id:$id})-[:HAS_ATTEMPT]->(:Attempt)-[:CAUSED_FAILURE]->(f:Failure) "
            "RETURN f ORDER BY f.discovered_at",
            {"id": step_id},
        )

    def events(self, run_id=None, after=0, limit=100, offset=0):
        if run_id:
            self.get_run(run_id)
        return self.store.nodes(
            'MATCH (e:Event) WHERE ($run="" OR e.run_id=$run) AND e.occurred_at >= $after '
            "RETURN e ORDER BY e.occurred_at,e.id SKIP $offset LIMIT $limit",
            {"run": run_id or "", "after": after, "limit": limit, "offset": offset},
        )

    def store_checkpoint(self, run_id):
        rows = self.store.query(
            """
            MATCH (r:AgentRun {id:$run})-[:HAS_STEP]->(s:Step)
            WITH r,collect({id:s.id,status:s.status,attempt:s.current_attempt_id}) AS state
            SET r.checkpoint_version=r.checkpoint_version+1,r.last_checkpoint_at=$now
            CREATE (r)-[:HAS_CHECKPOINT]->(c:Checkpoint {id:$id,run_id:r.id,version:r.checkpoint_version,
                current_goal:r.goal,created_at:$now,summary:'Persisted graph execution checkpoint',state_json:$state})
            RETURN c
            """,
            {
                "run": run_id,
                "id": uid(),
                "now": now(),
                "state": encode(
                    [
                        {k: s.get(k) for k in ["id", "status", "current_attempt_id"]}
                        for s in self.steps(run_id)
                    ]
                ),
            },
        )
        self.record_execution_event(run_id, "checkpoint_saved", "Execution checkpoint saved")
        # Flush the graph snapshot before acknowledging a durable checkpoint.
        # Compose uses RDB persistence after a reproduced upstream AOF replay crash.
        self.store.client.connection.save()
        return properties(rows[0][0])

    def get_resume_context(self, run_id):
        return {
            "run": self.get_run(run_id),
            "steps": self.steps(run_id),
            "checkpoint": self.checkpoint(run_id),
            "ready": self.get_ready_steps(run_id),
            "recent_events": self.events(run_id, limit=20),
        }

    def checkpoint(self, run_id):
        self.get_run(run_id)
        rows = self.store.nodes(
            "MATCH (:AgentRun {id:$run})-[:HAS_CHECKPOINT]->(c:Checkpoint) "
            "RETURN c ORDER BY c.version DESC LIMIT 1",
            {"run": run_id},
        )
        return rows[0] if rows else None

    def recover_interrupted_runs(self, run_id=None):
        rows = self.store.query(
            """
            MATCH (s:Step)-[:HAS_ATTEMPT]->(a:Attempt)
            WHERE ($run='' OR s.run_id=$run) AND s.status IN ['running','verifying']
            AND s.lease_until_ms<=$now AND s.current_attempt_id=a.id
            SET s.status='needs_reconciliation',s.lease_until_ms=0,s.updated_at=$now,
                a.status='interrupted',a.finished_at=$now
            RETURN s
            """,
            {"run": run_id or "", "now": now()},
        )
        for row in rows:
            s = properties(row[0])
            self.record_execution_event(
                s["run_id"],
                "worker_interrupted",
                "Lease expired; reconcile before retry",
                s["id"],
                s["current_attempt_id"],
                "recovery",
            )
        return [properties(row[0]) for row in rows]

    def reconcile(self, step_id, passed, evidence, safe_retry=False, artifact=None):
        target = "succeeded" if passed else ("retryable" if safe_retry else "failed")
        result = self.store.query(
            """
            MATCH (r:AgentRun)-[:HAS_STEP]->(s:Step {id:$id})-[:HAS_ATTEMPT]->(a:Attempt {id:$attempt})
            WHERE s.status='needs_reconciliation' AND s.current_attempt_id=a.id
            SET s.status=$target,s.verification_status=$verification,s.updated_at=$now,
                s.completed_at=$completed,a.verification_result=$evidence
            FOREACH (props IN $artifacts | CREATE (s)-[:PRODUCED]->(artifact:Artifact) SET artifact=props)
            CREATE (r)-[:RECORDED_EVENT]->(e:Event {id:$event,run_id:r.id,step_id:s.id,
                attempt_id:a.id,event_type:'reconciliation_completed',actor_id:'recovery',
                occurred_at:$now,summary:$summary,payload_reference:$evidence})
            CREATE (s)-[:HAS_DECISION]->(d:Decision {id:$decision,run_id:r.id,action:$target,
                decision_type:'reconciliation',actor_id:'recovery',created_at:$now,
                rationale_summary:$summary,evidence_status:$evidence_status,
                query_trace:'Expired lease + local read-before-retry inspection'})
            CREATE (d)-[:BASED_ON]->(a) CREATE (d)-[:BASED_ON]->(e)
            RETURN s
            """,
            {
                "id": step_id,
                "attempt": self.get_step(step_id)["current_attempt_id"],
                "target": target,
                "verification": "passed" if passed else "unverified",
                "now": now(),
                "evidence": encode(evidence),
                "event": uid(),
                "decision": uid(),
                "summary": evidence["summary"],
                "completed": now() if passed else 0,
                "artifacts": [artifact] if passed and artifact else [],
                "evidence_status": "verified_from_graph"
                if passed
                else ("inferred_or_proposed" if safe_retry else "unknown"),
            },
        )
        if not result:
            raise Conflict("Step is no longer awaiting reconciliation")
        step = properties(result[0][0])
        return step

    def handoff_step(self, step_id, source, target, role):
        self.register_agent(target, role)
        s = self.get_step(step_id)
        context = dict(
            run_id=s["run_id"],
            step_id=step_id,
            status=s["status"],
            expected_output=s["expected_output"],
            pending_action=role,
            attempts=[a["id"] for a in self.attempts(step_id)],
            evidence=[f["id"] for f in self.failures(step_id)],
        )
        self.store.query(
            "MATCH (a:Agent {id:$source}), (b:Agent {id:$target}) "
            "CREATE (a)-[:HANDED_OFF_TO {id:$id,step_id:$step,created_at:$now,context_json:$context}]->(b)",
            {
                "source": source,
                "target": target,
                "id": uid(),
                "step": step_id,
                "now": now(),
                "context": encode(context),
            },
        )
        self.record_execution_event(
            s["run_id"], "agent_handoff", f"{source} → {target}", step_id, actor=source, payload=context
        )

    def store_fact(self, run_id, subject, predicate, value, source_reference, resource_id=None):
        fact = dict(
            id=uid(),
            run_id=run_id,
            subject=subject,
            predicate=predicate,
            value=value,
            confidence=1.0,
            source_reference=source_reference,
            learned_at=now(),
            valid_until=0,
            status="verified",
        )
        self.store.query(
            "MATCH (r:AgentRun {id:$run}) CREATE (f:Fact) SET f=$props CREATE (r)-[:LEARNED]->(f)",
            {"run": run_id, "props": fact},
        )
        if resource_id:
            self.store.query(
                "MATCH (f:Fact {id:$id}), (r:Resource {id:$resource}) CREATE (f)-[:ABOUT]->(r)",
                {"id": fact["id"], "resource": resource_id},
            )
        return fact

    def recall_facts(self, run_id="", query="", limit=20):
        return self.store.nodes(
            "MATCH (f:Fact) WHERE ($run='' OR f.run_id=$run) "
            "AND (f.valid_until=0 OR f.valid_until>$now) AND f.status='verified' "
            'AND toLower(f.subject+" "+f.predicate+" "+f.value) CONTAINS toLower($query) '
            "RETURN f ORDER BY f.confidence DESC,f.learned_at DESC LIMIT $limit",
            {"run": run_id, "query": query, "limit": limit, "now": now()},
        )

    def retrieve_procedures(self, signature="", limit=20):
        return self.store.nodes(
            "MATCH (p:Procedure) WHERE ($sig='' OR p.problem_signature=$sig) "
            "RETURN p ORDER BY p.verified_success_count DESC,p.last_verified_at DESC LIMIT $limit",
            {"sig": signature, "limit": limit},
        )

    def explain_decision(self, decision_id):
        rows = self.store.query(
            "MATCH (d:Decision {id:$id}) OPTIONAL MATCH (d)-[r:BASED_ON]->(e) RETURN d,collect(e),collect(r)",
            {"id": decision_id},
            read=True,
        )
        if not rows:
            raise NotFound("Decision not found")
        d, nodes, edges = rows[0]
        return {
            "decision": properties(d),
            "sources": [properties(n) for n in nodes],
            "paths": [
                {"source": d.properties["id"], "relationship": "BASED_ON", "target": n.properties["id"]}
                for n in nodes
            ],
        }

    def decisions(self, run_id):
        self.get_run(run_id)
        return self.store.nodes(
            "MATCH (:AgentRun {id:$run})-[:HAS_STEP]->(:Step)-[:HAS_DECISION]->(d:Decision) "
            "RETURN d ORDER BY d.created_at DESC LIMIT 100",
            {"run": run_id},
        )

    def get_execution_graph(self, run_id, limit=300):
        self.get_run(run_id)
        # Bound all routine graph exports to one run, plus directly attached shared entities.
        rows = self.store.query(
            """
            MATCH (n) WHERE n.id=$run OR n.run_id=$run
            OPTIONAL MATCH (n)-[e]->(m)
            RETURN n,e,m LIMIT $limit
            """,
            {"run": run_id, "limit": limit},
            read=True,
        )
        rows += self.store.query(
            "MATCH (p:Procedure)-[e:APPLIES_TO]->(f:Failure {run_id:$run}) RETURN p,e,f LIMIT $limit",
            {"run": run_id, "limit": limit},
            read=True,
        )
        rows += self.store.query(
            "MATCH (a:Agent)-[e:HANDED_OFF_TO]->(b:Agent) WHERE e.step_id IN $steps "
            "RETURN a,e,b LIMIT $limit",
            {"steps": [s["id"] for s in self.steps(run_id)], "limit": limit},
            read=True,
        )
        nodes, edges = {}, {}
        for n, e, m in rows:
            for node in [n, m]:
                if node:
                    p = properties(node)
                    nodes[p["id"]] = {"id": p["id"], "label": node.labels[0], "properties": p}
            if e:
                key = str(e.id)
                edges[key] = {
                    "id": key,
                    "source": n.properties["id"],
                    "target": m.properties["id"],
                    "label": e.relation,
                }
        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "limit": limit,
            "truncated": len(rows) >= limit,
        }

    def dependency_impact(self, step_id):
        step = self.get_step(step_id)
        rows = self.store.query(
            "MATCH p=(affected:Step)-[:DEPENDS_ON*1..30]->(s:Step {id:$id}) "
            "RETURN affected,nodes(p) LIMIT 300",
            {"id": step_id},
            read=True,
        )
        affected = [
            {"step": properties(r[0]), "path": [n.properties["id"] for n in r[1]], "depth": len(r[1]) - 1}
            for r in rows
        ]
        affected_ids = {r["step"]["id"] for r in affected}
        return {
            "failed_step": step,
            "directly_blocked": [r for r in affected if r["depth"] == 1],
            "transitively_affected": affected,
            "unaffected_completed": [
                s
                for s in self.steps(step["run_id"])
                if s["status"] == "succeeded" and s["id"] not in affected_ids and s["id"] != step_id
            ],
            "safe_to_execute": [
                r
                for r in self.get_ready_steps(step["run_id"])
                if r["step"]["id"] not in affected_ids and r["step"]["id"] != step_id
            ],
        }

    def invalidate_downstream(self, step_id):
        self.get_step(step_id)
        rows = self.store.query(
            "MATCH (s:Step)-[:DEPENDS_ON*1..30]->(:Step {id:$id}) "
            "WHERE s.verification_status='passed' SET s.verification_status='stale' RETURN DISTINCT s",
            {"id": step_id},
        )
        step = self.get_step(step_id)
        self.record_execution_event(
            step["run_id"],
            "verification_stale",
            "Downstream verification marked stale; attempts preserved",
            step_id,
        )
        return [properties(r[0]) for r in rows]

    def complete_run_if_done(self, run_id):
        rows = self.store.query(
            """
            MATCH (r:AgentRun {id:$run})-[:HAS_STEP]->(s:Step)
            WITH r,collect(s) AS steps
            WHERE r.status='running' AND all(s IN steps WHERE s.status='succeeded' AND s.verification_status='passed')
            SET r.status='completed',r.completed_at=$now,r.updated_at=$now,
                r.summary='All steps independently verified. Original failures and evidence preserved.' RETURN r
            """,
            {"run": run_id, "now": now()},
        )
        if rows:
            self.store_checkpoint(run_id)
            self.record_execution_event(run_id, "run_completed", "All steps independently verified")
        return bool(rows)
