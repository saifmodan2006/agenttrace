import hashlib
import json
import time
import uuid
from falkordb import FalkorDB
from redis.exceptions import ResponseError
from app.core.config import settings

LABELS = (
    "AgentRun",
    "Step",
    "Attempt",
    "Agent",
    "Event",
    "Failure",
    "Procedure",
    "Fact",
    "Artifact",
    "Decision",
    "Checkpoint",
    "Resource",
)


def uid():
    return str(uuid.uuid4())


def now():
    return int(time.time() * 1000)


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def properties(node):
    return dict(node.properties) if node is not None else None


class GraphStore:
    def __init__(self, tenant: str):
        self.tenant = tenant
        self.name = "agenttrace_" + hashlib.sha256(tenant.encode()).hexdigest()[:24]
        self.client = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            password=settings.falkordb_password or None,
            socket_connect_timeout=3,
            socket_timeout=10,
        )
        self.graph = self.client.select_graph(self.name)

    def query(self, query, params=None, read=False):
        method = self.graph.ro_query if read else self.graph.query
        return method(query, params or {}).result_set

    def nodes(self, query, params=None, read=True):
        return [properties(row[0]) for row in self.query(query, params, read)]

    def initialize(self):
        # Labels and identifiers below are server constants, never user input.
        for label in LABELS:
            try:
                self.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
            except ResponseError as exc:
                if "already indexed" not in str(exc).lower() and "already exists" not in str(exc).lower():
                    raise
        for label, field in [
            ("Step", "run_id"),
            ("Step", "status"),
            ("Event", "run_id"),
            ("Attempt", "step_id"),
            ("Failure", "run_id"),
            ("Checkpoint", "run_id"),
        ]:
            try:
                self.query(f"CREATE INDEX FOR (n:{label}) ON (n.{field})")
            except ResponseError as exc:
                if "already indexed" not in str(exc).lower() and "already exists" not in str(exc).lower():
                    raise
        for label in LABELS:
            try:
                self.client.connection.execute_command(
                    "GRAPH.CONSTRAINT", "CREATE", self.name, "UNIQUE", "NODE", label, "PROPERTIES", 1, "id"
                )
            except ResponseError as exc:
                if "already exists" not in str(exc).lower():
                    raise

    def ping(self):
        return self.query("RETURN 1", read=True) == [[1]]
