"""Only fixed argument-vector commands, in per-tenant/run disposable workspaces."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.core.config import ROOT, settings
from app.graph.store import now, uid


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default="calculator.py", max_length=200)
    command: str = "tests"
    patch: str = "addition-fix"


class ToolRegistry:
    def __init__(self, tenant, run_id):
        UUID(run_id)
        namespace = hashlib.sha256(tenant.encode()).hexdigest()[:24]
        self.workspace = settings.runtime_dir / namespace / run_id

    def prepare(self):
        if not self.workspace.exists():
            self.workspace.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                ROOT / "demo" / "broken-app",
                self.workspace,
                ignore=shutil.ignore_patterns("__pycache__", "dist"),
            )

    def path(self, relative):
        path = (self.workspace / relative).resolve()
        if not path.is_relative_to(self.workspace.resolve()) or Path(relative).is_absolute():
            raise ValueError("Path escapes the controlled workspace")
        return path

    def validate(self, tool, args):
        parsed = ToolInput.model_validate(args)
        self.path(parsed.path)
        if tool == "run_allowed_command" and parsed.command not in {"tests", "build"}:
            raise ValueError("Command is not allowlisted")
        if tool == "apply_approved_patch" and parsed.patch != "addition-fix":
            raise ValueError("Only the pre-approved addition repair is supported")
        if tool not in {
            "inspect_project",
            "read_file",
            "run_allowed_command",
            "run_tests",
            "build_project",
            "apply_approved_patch",
            "verify_file_exists",
            "inspect_artifact",
        }:
            raise ValueError("Tool not registered")
        return parsed

    def command(self, kind):
        vectors = {
            "tests": [sys.executable, "-B", "-m", "unittest", "discover", "-v"],
            "build": [sys.executable, "-B", "build.py"],
        }
        if kind not in vectors:
            raise ValueError("Command is not allowlisted")
        try:
            p = subprocess.run(
                vectors[kind], cwd=self.workspace, capture_output=True, text=True, timeout=20, shell=False
            )
            return {
                "exit_code": p.returncode,
                "output": (p.stdout + p.stderr)[:16000],
                "error": p.stderr[:16000] if p.returncode else "",
                "command": vectors[kind][1:],
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": 124,
                "output": "Allowlisted command timed out after 20 seconds",
                "error": "timeout",
            }

    def execute(self, tool, args):
        parsed = self.validate(tool, args)
        self.prepare()
        if tool == "inspect_project":
            output = "\n".join(
                sorted(str(p.relative_to(self.workspace)) for p in self.workspace.rglob("*") if p.is_file())
            )
        elif tool in {"read_file", "inspect_artifact"}:
            output = self.path(parsed.path).read_text()[:16000]
        elif tool == "verify_file_exists":
            if not self.path(parsed.path).is_file():
                return {"exit_code": 1, "output": "Required file does not exist", "error": parsed.path}
            output = f"File exists: {parsed.path}"
        elif tool in {"run_tests", "build_project", "run_allowed_command"}:
            kind = {"run_tests": "tests", "build_project": "build"}.get(tool, parsed.command)
            return self.command(kind)
        elif tool == "apply_approved_patch":
            path = self.path("calculator.py")
            content = path.read_text()
            if "return a - b" in content:
                path.write_text(content.replace("return a - b", "return a + b"))
                output = "Applied pre-approved addition-fix to calculator.py"
            elif "return a + b" in content:
                output = "Read-before-retry: approved patch already present"
            else:
                return {
                    "exit_code": 1,
                    "output": "Source differs from approved patch precondition",
                    "error": "patch-precondition",
                }
        return {"exit_code": 0, "output": output, "error": ""}

    def verify(self, step, execution=None):
        """Inspect real state; test tools get a fresh, independent subprocess."""
        tool = step["tool_name"]
        args = ToolInput.model_validate(json.loads(step["input_json"]))
        artifact = None
        execution_ok = execution is None or execution["exit_code"] == 0
        if tool in {"run_tests", "run_allowed_command"}:
            result = self.command("tests" if tool == "run_tests" else args.command)
            passed = result["exit_code"] == 0 and execution_ok
            summary = "Independent test process passed" if passed else "Independent test process failed"
            output = result["output"]
        elif tool == "build_project":
            p = self.path("dist/result.json")
            try:
                data = json.loads(p.read_text())
                passed = data.get("result") == 5 and data.get("verified") is True and execution_ok
            except (OSError, ValueError):
                passed = False
            output = p.read_text() if p.exists() else "Build artifact missing"
            summary = (
                "Build artifact independently inspected" if passed else "Build artifact invalid or missing"
            )
            if passed:
                content = p.read_bytes()
                artifact = dict(
                    id=uid(),
                    type="build",
                    filename="dist/result.json",
                    storage_reference=f"workspace://{step['run_id']}/dist/result.json",
                    checksum=hashlib.sha256(content).hexdigest(),
                    size=len(content),
                    mime_type="application/json",
                    created_at=now(),
                    run_id=step["run_id"],
                )
        elif tool == "apply_approved_patch":
            output = self.path("calculator.py").read_text()
            passed = "return a + b" in output and "return a - b" not in output and execution_ok
            summary = (
                "Approved source change independently inspected" if passed else "Approved patch not present"
            )
        elif tool == "inspect_project":
            passed = (
                all(self.path(p).is_file() for p in ["calculator.py", "test_calculator.py", "build.py"])
                and execution_ok
            )
            output = "Checked required project files on disk"
            summary = "Project files independently inspected" if passed else "Project is incomplete"
        else:
            p = self.path(args.path)
            passed = p.is_file() and execution_ok
            output = p.read_text()[:16000] if passed else "File missing"
            summary = "File independently inspected" if passed else "File verification failed"
        criteria = json.loads(step.get("success_criteria_json", "{}"))
        if "file_exists" in criteria:
            passed = passed and self.path(criteria["file_exists"]).is_file()
        if "contains" in criteria:
            passed = passed and str(criteria["contains"]) in output
        if "exit_code" in criteria and execution:
            passed = passed and execution["exit_code"] == criteria["exit_code"]
        signature = "unknown"
        if not passed and tool in {"run_tests", "run_allowed_command"}:
            source = self.path("calculator.py").read_text()
            if "return a - b" in source and "AssertionError" in output and "test_positive" in output:
                signature = "addition-defect"
        return (
            passed,
            {
                "summary": summary,
                "output": output,
                "signature": signature,
                "root_cause": "Addition implemented as subtraction"
                if signature == "addition-defect"
                else "See independent evidence",
                "checked_at": now(),
                "method": "independent tool inspection",
            },
            artifact,
        )
