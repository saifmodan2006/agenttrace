import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx


def test_authenticated_sse_replays_persisted_events(memory, run):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "EMBEDDED_WORKER": "0",
        "TENANT_TOKENS": memory.tenant + ":stream-token",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if httpx.get(url + "/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "SSE test server failed to start"
            time.sleep(0.1)
        assert httpx.get(url + "/api/events/stream", timeout=3).status_code == 401
        headers = {"Authorization": "Bearer stream-token"}
        expected = {e["id"] for e in memory.events(run["id"])}
        with httpx.stream("GET", url + "/api/events/stream?after=0", headers=headers, timeout=5) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            import json

            first = next(line for line in response.iter_lines() if line.startswith("data: "))
            assert json.loads(first[6:])["id"] in expected
    finally:
        server.terminate()
        server.wait(timeout=10)
