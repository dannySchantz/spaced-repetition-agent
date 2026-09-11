"""End-to-end isolated simulator transcript and review evidence."""

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["RECALL_LIVE_SMS"] = "false"
os.environ["RECALL_LIVE_AI"] = "false"
os.environ.pop("RECALL_TOKEN", None)

from recall.service import create_app

with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_app(Path(directory) / "demo.db")) as c:
        c.post("/v1/sms/setup-simulator")
        for term, definition in [
            ("kernel", "Inputs mapped to zero"),
            ("rank", "Dimension of the image"),
            ("eigenvector", "A nonzero vector scaled by a linear transformation."),
        ]:
            c.post("/v1/cards", json={"term": term, "definition": definition})

        def sms(body, key):
            result = c.post("/v1/sms/simulate", json={"body": body, "message_id": key})
            assert result.status_code == 200, result.text
            return result.json()

        messages = sms("MORE", "more")
        session = c.get("/v1/sessions").json()[0]
        answers = {
            "kernel": "Inputs mapped to zero",
            "rank": "Dimension of the image",
            "eigenvector": "A vector scaled by the matrix.",
        }
        initial = (
            session["code"]
            + " "
            + "; ".join(f"{e['ordinal']}) {answers[e['term']]}" for e in session["episodes"])
        )
        messages = sms(initial, "answers")
        eigen = next(e for e in session["episodes"] if e["term"] == "eigenvector")
        probe = f"{session['code']} {eigen['ordinal']}) It must be nonzero."
        messages = sms(probe, "probe")
        transcript = [
            "# Simulated SMS demonstration\n",
            "Local fixture provider; no real texts or paid calls.\n",
            "```text",
            "USER: MORE",
            "APP: " + messages[0]["body"],
            "USER: " + initial,
        ]
        transcript.extend("APP: " + m["body"] for m in messages[1:-1])
        transcript.extend(
            ["USER: " + probe, "APP: " + messages[-1]["body"], "```", "\nEffective review history:"]
        )
        history = c.get("/v1/history").json()
        for review in history:
            transcript.append(
                f"- {review['term']}: rating {review['rating']} ({review['source']}); first answer: {review['initial_answer']}"
            )
        assert (
            len(history) == 3
            and next(r for r in history if r["term"] == "eigenvector")["rating"] == 1
        )
        output = "\n".join(transcript) + "\n"
        Path("docs/simulator-transcript.md").write_text(output)
        print(output)
