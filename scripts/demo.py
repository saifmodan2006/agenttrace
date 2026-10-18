"""HTTP-only reproducible demo; uses the same API as the dashboard."""

import argparse
import os
import time
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
args = parser.parse_args()
headers = {
    "Authorization": "Bearer " + os.environ.get("AGENTTRACE_TOKEN", "local-demo-token")
}
with httpx.Client(base_url=args.url, headers=headers, timeout=30) as client:
    response = client.post(
        "/api/runs",
        json={"goal": "Broken Application: Autonomous Diagnosis and Recovery"},
    )
    response.raise_for_status()
    run = response.json()["data"]
    rid = run["id"]
    client.post("/api/runs/" + rid + "/start").raise_for_status()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = client.get("/api/runs/" + rid).json()["data"]
        steps = client.get("/api/runs/" + rid + "/steps").json()["data"]
        print(
            run["status"],
            ", ".join(s["key"] + ":" + s["status"] for s in steps),
            flush=True,
        )
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.5)
    assert run["status"] == "completed", run
    failed = next(s for s in steps if s["key"] == "tests")
    attempts = client.get("/api/steps/" + failed["id"] + "/attempts").json()["data"]
    assert (
        len(attempts) == 2
        and attempts[0]["exit_code"] != 0
        and attempts[1]["status"] == "succeeded"
    )
    decisions = client.get("/api/runs/" + rid + "/explanations").json()["data"]
    recovery = next(d for d in decisions if d["decision_type"] == "recovery")
    evidence = client.get("/api/decisions/" + recovery["id"]).json()["data"]
    assert len(evidence["sources"]) == 2
    print("Verified run:", rid)
    print("Recovery evidence:", [s["id"] for s in evidence["sources"]])
    print(
        "Restart demonstration: run backend/tests/test_restart.py; it kills and restarts real worker processes."
    )
