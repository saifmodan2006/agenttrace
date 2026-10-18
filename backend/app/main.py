import asyncio
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from redis.exceptions import RedisError
from app.agents.planner import PlannerAgent
from app.core.config import settings
from app.graph.store import now
from app.memory.manager import AgentMemoryManager, Conflict, NotFound
from app.models.schemas import RunCreate, ClaimRequest, LeaseRequest
from app.security.auth import memory, require_worker, tenants
from app.workers.runner import Worker

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()
    threads = []
    for tenant in tenants():
        m = AgentMemoryManager(tenant)
        m.initialize()
        if os.environ.get("EMBEDDED_WORKER", "1") == "1":
            worker = Worker(m, "executor-api", stop)
            thread = threading.Thread(target=worker.loop, daemon=True)
            thread.start()
            threads.append(thread)
    yield
    stop.set()
    for thread in threads:
        thread.join(timeout=25)


app = FastAPI(
    title="AgentTrace",
    version="0.1.0",
    lifespan=lifespan,
    description="Graph-native execution memory. All application routes require a tenant bearer token.",
)


def envelope(data, privileged=False, **meta):
    def redact(value):
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items() if k not in {"lease_token"}}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value

    return {"data": data if privileged else redact(data), "meta": meta}


@app.exception_handler(NotFound)
async def not_found(request, exc):
    return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": str(exc)}})


@app.exception_handler(Conflict)
async def conflict(request, exc):
    return JSONResponse(status_code=409, content={"error": {"code": "conflict", "message": str(exc)}})


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(exc)}})


@app.exception_handler(RedisError)
async def unavailable(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "error": {"code": "graph_unavailable", "message": "FalkorDB unavailable; scheduling stopped"}
        },
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(
        status_code=exc.status_code, content={"error": {"code": "http_error", "message": str(exc.detail)}}
    )


@app.exception_handler(RequestValidationError)
async def schema_error(request, exc):
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": str(exc)}})


@app.get("/api/health")
def health():
    try:
        configured_tenant = next(iter(tenants()), None)
        if not configured_tenant:
            raise HTTPException(503, "No tenant configured")
        ok = AgentMemoryManager(configured_tenant).store.ping()
        return envelope(
            {"status": "healthy" if ok else "degraded", "database": "connected", "checked_at": now()}
        )
    except RedisError:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "graph_unavailable", "message": "Database disconnected"}},
        )


@app.get("/api/config/status")
def config_status(m=Depends(memory)):
    return envelope(
        {
            "database": "connected" if m.store.ping() else "disconnected",
            "llm_configured": bool(settings.llm_base_url and settings.llm_model),
            "llm_model": settings.llm_model or None,
            "default_mode": "demo",
            "lease_ms": settings.lease_ms,
            "worker_poll_seconds": settings.worker_poll_seconds,
            "tenant": m.tenant,
            "retention": "Persistent until explicitly deleted; no automatic pruning",
        }
    )


@app.post("/api/runs", status_code=201)
def create_run(body: RunCreate, m=Depends(memory)):
    if body.mode == "llm" and not (settings.llm_base_url and settings.llm_model):
        raise HTTPException(422, "Live planning is not configured")
    run = m.create_run(body.goal, body.description, body.mode)
    try:
        PlannerAgent(m).plan(run)
    except Exception:
        m.store.query(
            "MATCH (r:AgentRun {id:$id}) SET r.status='failed',r.summary='Planning failed; see server logs'",
            {"id": run["id"]},
        )
        raise
    return envelope(m.get_run(run["id"]))


@app.get("/api/runs")
def runs(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), m=Depends(memory)):
    return envelope(m.list_runs(limit, offset), limit=limit, offset=offset)


@app.get("/api/runs/{run_id}")
def run(run_id: UUID, m=Depends(memory)):
    return envelope(m.get_run(str(run_id)))


@app.post("/api/runs/{run_id}/start")
def start(run_id: UUID, m=Depends(memory)):
    return envelope(m.set_run_status(str(run_id), "running"))


@app.post("/api/runs/{run_id}/pause")
def pause(run_id: UUID, m=Depends(memory)):
    result = m.set_run_status(str(run_id), "paused")
    m.store_checkpoint(str(run_id))
    return envelope(result)


@app.post("/api/runs/{run_id}/resume")
def resume(run_id: UUID, m=Depends(memory)):
    m.get_run(str(run_id))
    m.recover_interrupted_runs(str(run_id))
    m.set_run_status(str(run_id), "running")
    return envelope(m.get_resume_context(str(run_id)))


@app.get("/api/runs/{run_id}/steps")
def steps(run_id: UUID, m=Depends(memory)):
    return envelope(m.steps(str(run_id)))


@app.get("/api/runs/{run_id}/ready")
def ready(run_id: UUID, m=Depends(memory)):
    return envelope(m.get_ready_steps(str(run_id)))


@app.get("/api/runs/{run_id}/graph")
def graph(run_id: UUID, limit: int = Query(300, ge=1, le=1000), m=Depends(memory)):
    return envelope(m.get_execution_graph(str(run_id), limit))


@app.get("/api/runs/{run_id}/blocked")
def blocked(run_id: UUID, m=Depends(memory)):
    return envelope(m.get_blocked_steps(str(run_id)))


@app.get("/api/runs/{run_id}/events")
def events(
    run_id: UUID,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    m=Depends(memory),
):
    return envelope(m.events(str(run_id), after, limit, offset), limit=limit, offset=offset)


@app.get("/api/runs/{run_id}/checkpoint")
def checkpoint(run_id: UUID, m=Depends(memory)):
    return envelope(m.checkpoint(str(run_id)))


@app.get("/api/runs/{run_id}/explanations")
def explanations(run_id: UUID, m=Depends(memory)):
    return envelope(m.decisions(str(run_id)))


@app.get("/api/decisions/{decision_id}")
def decision(decision_id: UUID, m=Depends(memory)):
    return envelope(m.explain_decision(str(decision_id)))


@app.get("/api/steps/{step_id}")
def step(step_id: UUID, m=Depends(memory)):
    return envelope(m.get_step(str(step_id)))


@app.get("/api/steps/{step_id}/attempts")
def attempts(step_id: UUID, m=Depends(memory)):
    return envelope(m.attempts(str(step_id)))


@app.get("/api/steps/{step_id}/failures")
def failures(step_id: UUID, m=Depends(memory)):
    return envelope(m.failures(str(step_id)))


@app.get("/api/steps/{step_id}/impact")
def impact(step_id: UUID, m=Depends(memory)):
    return envelope(m.dependency_impact(str(step_id)))


@app.post("/api/steps/{step_id}/invalidate", dependencies=[Depends(require_worker)])
def invalidate(step_id: UUID, m=Depends(memory)):
    return envelope(m.invalidate_downstream(str(step_id)))


@app.get("/api/memory/search")
def search(
    query: str = Query("", max_length=500),
    run_id: str = "",
    current_step_id: str = "",
    memory_types: str = "episodic,semantic,procedural",
    result_limit: int = Query(20, ge=1, le=100),
    m=Depends(memory),
):
    if current_step_id:
        step = m.get_step(current_step_id)
        if run_id and run_id != step["run_id"]:
            raise HTTPException(422, "Step does not belong to requested run")
        run_id = step["run_id"]
    if run_id:
        m.get_run(run_id)
    result = []
    if "semantic" in memory_types:
        result.extend(dict(type="semantic", record=f) for f in m.recall_facts(run_id, query, result_limit))
    if "procedural" in memory_types:
        # Scope procedures through their actual failure relationships when a run is supplied.
        procedures = m.store.nodes(
            "MATCH (p:Procedure)-[:APPLIES_TO]->(f:Failure) "
            "WHERE ($run='' OR f.run_id=$run) AND toLower(p.name) CONTAINS toLower($query) "
            "RETURN DISTINCT p ORDER BY p.verified_success_count DESC LIMIT $limit",
            {"run": run_id, "query": query, "limit": result_limit},
        )
        result.extend(dict(type="procedural", record=p) for p in procedures)
    if "episodic" in memory_types:
        records = m.store.nodes(
            "MATCH (e:Event) WHERE ($run='' OR e.run_id=$run) "
            "AND toLower(e.summary) CONTAINS toLower($query) RETURN e "
            "ORDER BY e.occurred_at DESC LIMIT $limit",
            {"run": run_id, "query": query, "limit": result_limit},
        )
        result.extend(dict(type="episodic", record=e) for e in records)
    return envelope(
        result[:result_limit],
        ranking="Verified semantic facts, then applicable procedures, then recent episodes",
    )


@app.get("/api/memory/procedures")
def procedures(m=Depends(memory)):
    return envelope(m.retrieve_procedures())


@app.get("/api/agents")
def agents(m=Depends(memory)):
    return envelope(m.store.nodes("MATCH (a:Agent) RETURN a ORDER BY a.role"))


@app.get("/api/overview")
def overview(m=Depends(memory)):
    counts = m.store.query("MATCH (s:Step) RETURN s.status,count(s)", read=True)
    runs = m.store.query("MATCH (r:AgentRun) RETURN r.status,count(r)", read=True)
    failed = m.store.query("MATCH (f:Failure) RETURN count(f)", read=True)[0][0]
    recovered = m.store.query("MATCH (f:Failure) WHERE f.resolved_at>0 RETURN count(f)", read=True)[0][0]
    blocked_count = m.store.query(
        "MATCH (s:Step)-[:DEPENDS_ON]->(d:Step) "
        "WHERE s.status IN ['pending','ready','retryable','blocked'] "
        "AND (d.status<>'succeeded' OR d.verification_status<>'passed') "
        "RETURN count(DISTINCT s)",
        read=True,
    )[0][0]
    recent = m.store.nodes("MATCH (e:Event) RETURN e ORDER BY e.occurred_at DESC LIMIT 12")
    return envelope(
        {
            "steps": dict(counts),
            "runs": dict(runs),
            "failed_attempts": failed,
            "recoveries": recovered,
            "dependency_blocked": blocked_count,
            "recent_events": recent,
        }
    )


@app.get("/api/events/stream")
async def stream(request: Request, after: int = Query(0, ge=0), m=Depends(memory)):
    async def generate():
        cursor, seen = after, set()
        while not await request.is_disconnected():
            offset = 0
            next_cursor, next_seen = cursor, set(seen)
            while True:
                batch = await asyncio.to_thread(m.events, None, cursor, 200, offset)
                for event in batch:
                    if event["id"] not in seen:
                        yield "id: " + str(event["occurred_at"]) + "\ndata: " + json.dumps(event) + "\n\n"
                    if event["occurred_at"] > next_cursor:
                        next_cursor, next_seen = event["occurred_at"], set()
                    if event["occurred_at"] == next_cursor:
                        next_seen.add(event["id"])
                if len(batch) < 200:
                    break
                offset += 200
            cursor, seen = next_cursor, next_seen
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/internal/claim", dependencies=[Depends(require_worker)])
def claim(body: ClaimRequest, m=Depends(memory)):
    m.get_run(body.run_id)
    step = m.get_step(body.step_id)
    if step["run_id"] != body.run_id:
        raise HTTPException(422, "Step belongs to another run")
    m.register_agent(body.worker_id)
    result = m.claim_step(body.run_id, body.step_id, body.worker_id, settings.lease_ms)
    if not result:
        raise Conflict("Task not eligible or already claimed")
    return envelope(result, privileged=True)


@app.post("/api/internal/heartbeat", dependencies=[Depends(require_worker)])
def heartbeat(body: LeaseRequest, m=Depends(memory)):
    return envelope(
        m.renew_lease(body.step_id, body.attempt_id, body.worker_id, body.lease_token, settings.lease_ms)
    )


@app.post("/api/internal/attempts/complete", dependencies=[Depends(require_worker)])
def complete(body: LeaseRequest, m=Depends(memory)):
    m.renew_lease(body.step_id, body.attempt_id, body.worker_id, body.lease_token, settings.lease_ms)
    step = m.get_step(body.step_id)
    attempt = next(a for a in m.attempts(body.step_id) if a["id"] == body.attempt_id)
    # This endpoint executes the registered tool itself. It cannot accept invented results.
    Worker(m, body.worker_id).execute_claim({"step": step, "attempt": attempt})
    return envelope(m.get_step(body.step_id))


@app.post("/api/internal/verify", dependencies=[Depends(require_worker)])
def verify(body: LeaseRequest, m=Depends(memory)):
    from app.tools.registry import ToolRegistry

    m.renew_lease(body.step_id, body.attempt_id, body.worker_id, body.lease_token, settings.lease_ms)
    step = m.get_step(body.step_id)
    attempt = next(a for a in m.attempts(body.step_id) if a["id"] == body.attempt_id)
    passed, evidence, artifact = ToolRegistry(m.tenant, step["run_id"]).verify(
        step, {"exit_code": attempt.get("exit_code", 1)}
    )
    return envelope(
        m.verify_step(
            body.step_id, body.attempt_id, body.worker_id, body.lease_token, passed, evidence, artifact
        )
    )
