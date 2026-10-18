from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

TOOLS = {
    "inspect_project",
    "read_file",
    "run_allowed_command",
    "run_tests",
    "build_project",
    "apply_approved_patch",
    "verify_file_exists",
    "inspect_artifact",
}


class Status(StrEnum):
    pending = "pending"
    ready = "ready"
    running = "running"
    verifying = "verifying"
    succeeded = "succeeded"
    retryable = "retryable"
    failed = "failed"
    blocked = "blocked"
    needs_reconciliation = "needs_reconciliation"
    cancelled = "cancelled"


TRANSITIONS = {
    "pending": {"ready", "running", "blocked", "cancelled"},
    "ready": {"running", "blocked", "cancelled"},
    "running": {"verifying", "retryable", "failed", "needs_reconciliation"},
    "verifying": {"succeeded", "retryable", "failed", "needs_reconciliation"},
    "retryable": {"ready", "running", "failed", "cancelled"},
    "needs_reconciliation": {"succeeded", "retryable", "failed"},
    "blocked": {"ready", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


class StepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1000)
    tool_name: str
    input: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    priority: int = Field(default=0, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=5)
    success_criteria: dict = Field(default_factory=lambda: {"exit_code": 0})


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[StepSpec] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid_dag(self):
        by_key = {s.key: s for s in self.steps}
        if len(by_key) != len(self.steps):
            raise ValueError("Duplicate step keys")
        visiting, visited = set(), set()

        def visit(key):
            if key not in by_key:
                raise ValueError(f"Unknown dependency: {key}")
            if key in visiting:
                raise ValueError("Cyclic dependency")
            if key in visited:
                return
            visiting.add(key)
            for dep in by_key[key].depends_on:
                visit(dep)
            visiting.remove(key)
            visited.add(key)

        for step in self.steps:
            if step.tool_name not in TOOLS:
                raise ValueError(f"Unsupported tool: {step.tool_name}")
            visit(step.key)
        return self


class RunCreate(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    description: str = Field(default="", max_length=4000)
    mode: Literal["demo", "llm"] = "demo"
    scenario: Literal["broken-app"] = "broken-app"


class ClaimRequest(BaseModel):
    run_id: str
    step_id: str
    worker_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")


class LeaseRequest(BaseModel):
    step_id: str
    attempt_id: str
    lease_token: str
    worker_id: str
