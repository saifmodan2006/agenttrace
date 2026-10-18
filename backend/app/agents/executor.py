import json
from app.tools.registry import ToolRegistry


class ExecutorAgent:
    def __init__(self, memory, agent_id):
        self.memory = memory
        self.agent_id = agent_id

    def execute(self, step):
        self.memory.heartbeat(self.agent_id)
        registry = ToolRegistry(self.memory.tenant, step["run_id"])
        return registry.execute(step["tool_name"], json.loads(step["input_json"]))
