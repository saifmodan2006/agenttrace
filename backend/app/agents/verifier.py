from app.tools.registry import ToolRegistry


class VerifierAgent:
    def __init__(self, memory):
        self.memory = memory

    def verify(self, step, execution):
        self.memory.heartbeat("verifier")
        return ToolRegistry(self.memory.tenant, step["run_id"]).verify(step, execution)
