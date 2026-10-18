import httpx
from app.core.config import settings
from app.models.schemas import Plan
from app.tools.registry import ToolRegistry

DEMO_PLAN = {
    "steps": [
        {
            "key": "inspect",
            "title": "Inspect application",
            "objective": "Locate source, tests, and build script",
            "tool_name": "inspect_project",
            "priority": 100,
        },
        {
            "key": "tests",
            "title": "Validate calculator",
            "objective": "All three calculator tests pass",
            "tool_name": "run_tests",
            "depends_on": ["inspect"],
            "priority": 90,
        },
        {
            "key": "build",
            "title": "Build verified artifact",
            "objective": "Produce a result artifact with result = 5",
            "tool_name": "build_project",
            "depends_on": ["tests"],
            "priority": 80,
            "success_criteria": {"exit_code": 0, "file_exists": "dist/result.json"},
        },
        {
            "key": "evidence",
            "title": "Inspect final evidence",
            "objective": "Read the actual build artifact",
            "tool_name": "inspect_artifact",
            "input": {"path": "dist/result.json"},
            "depends_on": ["build"],
            "success_criteria": {"contains": '"result": 5'},
        },
        {
            "key": "source",
            "title": "Check source provenance",
            "objective": "Inspect the original controlled source",
            "tool_name": "read_file",
            "input": {"path": "calculator.py"},
            "depends_on": ["inspect"],
            "priority": 10,
        },
    ]
}


class PlannerAgent:
    def __init__(self, memory):
        self.memory = memory

    def plan(self, run):
        self.memory.register_agent("planner", "planner")
        if run["mode"] == "demo":
            plan = Plan.model_validate(DEMO_PLAN)
        else:
            if not settings.llm_base_url or not settings.llm_model:
                raise ValueError("Set LLM_BASE_URL and LLM_MODEL before using live planning")
            headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
            prompt = (
                "Create a safe plan for the isolated calculator application. Source has add(a,b), "
                "tests and build.py. Only registered tools are permitted. No shell commands. "
                "Do not apply patches before obtaining failing test evidence. "
                "Tool inputs may only have path, command (tests/build), patch (addition-fix). "
                "Return JSON matching this schema: " + str(Plan.model_json_schema())
            )
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    settings.llm_base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json={
                        "model": settings.llm_model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": run["goal"]},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
                plan = Plan.model_validate_json(response.json()["choices"][0]["message"]["content"])
        registry = ToolRegistry(self.memory.tenant, run["id"])
        for step in plan.steps:
            registry.validate(step.tool_name, step.input)
            if step.tool_name == "apply_approved_patch":
                raise ValueError("Repairs require recorded failure evidence; planner cannot authorize them")
            if not set(step.success_criteria) <= {"exit_code", "file_exists", "contains"}:
                raise ValueError("Unsupported success criterion")
            if "file_exists" in step.success_criteria:
                registry.path(step.success_criteria["file_exists"])
        return self.memory.create_plan(run["id"], plan)
