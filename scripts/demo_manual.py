"""Run an isolated real-service/CLI study and restart demonstration, without credentials."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

with tempfile.TemporaryDirectory() as directory:
    env = {
        **os.environ,
        "RECALL_DB": str(Path(directory) / "recall.db"),
        "RECALL_URL": "http://127.0.0.1:18765",
        "RECALL_TOKEN": "",
        "RECALL_LIVE_SMS": "false",
        "RECALL_LIVE_AI": "false",
    }
    executable = str(Path(sys.executable).with_name("recall"))

    def launch():
        process = subprocess.Popen(
            [executable, "serve", "--port", "18765"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                if httpx.get(env["RECALL_URL"] + "/v1/health").status_code == 200:
                    return process
            except httpx.ConnectError:
                pass
            time.sleep(0.05)
        process.terminate()
        raise RuntimeError("Service failed to start")

    p = launch()
    try:
        for args, data in [
            (["doctor"], None),
            (["add", "kernel", "Inputs mapped to zero"], None),
            (["review"], "\n3\n"),
        ]:
            result = subprocess.run(
                [executable, *args], input=data, text=True, env=env, capture_output=True, check=True
            )
            print(result.stdout)
        before = httpx.get(env["RECALL_URL"] + "/v1/history").json()
        p.terminate()
        p.wait(timeout=10)
        p = launch()
        after = httpx.get(env["RECALL_URL"] + "/v1/history").json()
        assert before == after and len(after) == 1
        print("Restart preserved one review and exact FSRS state.")
    finally:
        p.terminate()
        p.wait(timeout=10)
