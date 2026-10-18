import shutil
import uuid
import pytest
from app.memory.manager import AgentMemoryManager
from app.core.config import settings
from app.agents.planner import PlannerAgent
from app.tools.registry import ToolRegistry


@pytest.fixture
def memory():
    m = AgentMemoryManager("test-" + uuid.uuid4().hex)
    m.initialize()
    yield m
    for run in m.list_runs():
        workspace = ToolRegistry(m.tenant, run["id"]).workspace
        if workspace.exists() and workspace.resolve().is_relative_to(settings.runtime_dir.resolve()):
            shutil.rmtree(workspace)
    m.store.graph.delete()


@pytest.fixture
def run(memory):
    r = memory.create_run("Repair the controlled broken application")
    PlannerAgent(memory).plan(r)
    memory.set_run_status(r["id"], "running")
    return r
