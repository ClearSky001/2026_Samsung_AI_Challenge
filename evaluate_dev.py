#!/usr/bin/env python3
"""Run the harness on dev_tasks and score it with the provided local scorer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import scoring
from harness import FinalHarness


def load_jsonl(path: Path):
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dev_tasks", type=Path)
    parser.add_argument("dev_answers", type=Path)
    args = parser.parse_args()

    tasks = load_jsonl(args.dev_tasks)
    answers = json.loads(args.dev_answers.read_text(encoding="utf-8"))
    payload = scoring.run_harness(tasks, FinalHarness, harness_name="scpc2026_generalized_dev")
    scoring.validate_payload(payload, {str(task["id"]) for task in tasks})
    report = scoring.score_dev_submission(payload, answers)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
