"""Offline fixture contract evaluation; live quality evaluation is explicitly opt-in."""

import argparse
import hashlib
import json
from pathlib import Path

from recall.ai.grader import PROMPT_VERSION, FixtureProvider, GradeBatch, OpenAIProvider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="Authorizes paid API requests for this evaluation"
    )
    parser.add_argument("--model")
    parser.add_argument("--split", choices=["all", "development", "held_out"], default="all")
    parser.add_argument("--output", default="evals/last-result.json")
    args = parser.parse_args()
    path = Path(__file__).with_name("grader_cases.jsonl")
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    cases = [c for c in cases if args.split == "all" or c["split"] == args.split]
    provider = OpenAIProvider(args.model, authorized=True) if args.live else FixtureProvider()
    comparisons = []
    for case in cases:
        item = {
            "episode_id": case["id"],
            "term": case["term"],
            "context": case["context"],
            "reference": case["reference"],
            "answer": case["answer"],
            "kind": "initial",
            "rubric": [],
        }
        response = provider.grade([item])
        actual = GradeBatch.model_validate(response.data).validate_ids([case["id"]]).results[0]
        comparisons.append(
            {
                "id": case["id"],
                "split": case["split"],
                "expected": case["expected"],
                "actual": actual.model_dump(),
                "agreement": actual.verdict == case["expected"]["verdict"],
                "must_fail": case["must_fail"],
                "usage": response.usage,
            }
        )
    clear = [c for c in comparisons if c["expected"]["verdict"] != "ungraded"]
    agreement = sum(c["agreement"] for c in clear) / len(clear)
    false_right = [
        c["id"] for c in comparisons if c["must_fail"] and c["actual"]["verdict"] == "right"
    ]
    report = {
        "mode": "live" if args.live else "fixture_contract_only",
        "model": args.model if args.live else "offline-fixtures-v1",
        "prompt_version": PROMPT_VERSION,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "count": len(cases),
        "split": args.split,
        "clear_agreement": agreement,
        "false_right_must_fail": false_right,
        "numeric_gate": agreement >= 0.95 and not false_right,
        "human_reviewed": False,
        "comparisons": comparisons,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{report['mode']}: {len(cases)} cases; agreement {agreement:.1%}; must-fail false Right {len(false_right)}"
    )
    print(
        "Human label review and inspection of every probe/disagreement remain required. Fixture replay does not establish live model quality."
    )
    if not report["numeric_gate"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
