#!/usr/bin/env python3
"""Generate a SCPC 2026 submission.csv with the generalized FinalHarness."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from harness import FIXED_SLM_ID, SUBMISSION_SCHEMA, FinalHarness


REMOVED_SCORING_KEYS = ("expected_events", "answer")
VALID_CONTROLS = {"proceed", "amend", "hold", "ask"}
VALID_SCOPE_MODES = {"raw", "summary", "redacted", "status_only", "none"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def participant_task_view(task: dict[str, Any]) -> dict[str, Any]:
    view = json.loads(json.dumps(task, ensure_ascii=False))
    for key in list(view):
        if (
            key in REMOVED_SCORING_KEYS
            or key.startswith("expected_")
            or key.endswith("_brief")
            or key.endswith("_notes")
            or key.endswith("_rubric")
            or key.endswith("_keywords")
            or key.endswith("_tags")
        ):
            view.pop(key, None)
    return view


def run_harness(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        tasks,
        key=lambda task: (
            str(task.get("session_id", "")),
            int(task.get("turn_index", 0)),
            str(task.get("id", "")),
        ),
    )
    harness = FinalHarness()
    harness.prepare([])
    sessions: dict[str, dict[str, Any]] = {}
    answers: dict[str, dict[str, Any]] = {}
    for task in ordered:
        session = sessions.setdefault(str(task.get("session_id", "")), {})
        answers[str(task["id"])] = harness.answer_task(participant_task_view(task), session)
    return {
        "schema": SUBMISSION_SCHEMA,
        "meta": {
            "harness_name": "scpc2026_generalized_v2",
            "uses_external_api": False,
            "fixed_slm_policy": "local_fixed_slm_only",
            "model_id": FIXED_SLM_ID,
            "temperature": 0.0,
            "seed": 42,
        },
        "answers": answers,
    }


def validate(payload: dict[str, Any], tasks: list[dict[str, Any]]) -> None:
    if payload.get("schema") != SUBMISSION_SCHEMA:
        raise ValueError("invalid submission schema")
    meta = payload.get("meta") or {}
    if meta.get("uses_external_api") is not False:
        raise ValueError("uses_external_api must be false")
    if meta.get("fixed_slm_policy") != "local_fixed_slm_only":
        raise ValueError("invalid fixed_slm_policy")
    if meta.get("model_id") != FIXED_SLM_ID:
        raise ValueError("invalid model_id")

    expected_ids = {str(task["id"]) for task in tasks}
    answers = payload.get("answers")
    if not isinstance(answers, dict) or set(answers) != expected_ids:
        missing = sorted(expected_ids - set(answers or {}))
        extra = sorted(set(answers or {}) - expected_ids)
        raise ValueError(f"answer id mismatch: missing={missing[:3]}, extra={extra[:3]}")

    objects_by_task = {
        str(task["id"]): {
            str(obj.get("id"))
            for obj in ((task.get("device_state") or {}).get("objects") or [])
        }
        for task in tasks
    }
    required = {"focal_id", "target", "control", "content_scope", "policy", "plan_events"}
    for task_id, answer in answers.items():
        if not isinstance(answer, dict) or not required <= set(answer):
            raise ValueError(f"missing required answer fields: {task_id}")
        if answer["focal_id"] not in objects_by_task[task_id]:
            raise ValueError(f"focal_id is not a task object: {task_id}")
        if not isinstance(answer.get("target"), str) or not answer["target"]:
            raise ValueError(f"invalid target: {task_id}")
        if answer["control"] not in VALID_CONTROLS:
            raise ValueError(f"invalid control: {task_id}")
        scope = answer.get("content_scope") or {}
        scope_required = {"mode", "allowed_fields", "excluded_fields", "requires_user_confirmation"}
        if not scope_required <= set(scope) or scope.get("mode") not in VALID_SCOPE_MODES:
            raise ValueError(f"invalid scope mode: {task_id}")
        if not isinstance(scope["allowed_fields"], list) or not all(isinstance(x, str) for x in scope["allowed_fields"]):
            raise ValueError(f"invalid allowed_fields: {task_id}")
        if not isinstance(scope["excluded_fields"], list) or not all(isinstance(x, str) for x in scope["excluded_fields"]):
            raise ValueError(f"invalid excluded_fields: {task_id}")
        if not isinstance(scope["requires_user_confirmation"], bool):
            raise ValueError(f"invalid scope confirmation: {task_id}")
        policy = answer.get("policy") or {}
        policy_required = {"risk_flags", "violations", "requires_confirmation"}
        if not policy_required <= set(policy):
            raise ValueError(f"invalid policy: {task_id}")
        if not isinstance(policy["risk_flags"], list) or not all(isinstance(x, str) for x in policy["risk_flags"]):
            raise ValueError(f"invalid risk_flags: {task_id}")
        if not isinstance(policy["violations"], list) or not all(isinstance(x, str) for x in policy["violations"]):
            raise ValueError(f"invalid violations: {task_id}")
        if not isinstance(policy["requires_confirmation"], bool):
            raise ValueError(f"invalid policy confirmation: {task_id}")
        events = answer.get("plan_events")
        if not isinstance(events, list) or len(events) > 18:
            raise ValueError(f"invalid plan_events: {task_id}")
        for event in events:
            if not isinstance(event, dict) or not {"verb", "target", "args"} <= set(event):
                raise ValueError(f"invalid event: {task_id}")
            if not isinstance(event["verb"], str) or not isinstance(event["target"], str) or not isinstance(event["args"], dict):
                raise ValueError(f"invalid event types: {task_id}")


def write_submission(payload: dict[str, Any], output: Path) -> None:
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["submission"])
        writer.writerow([json.dumps(payload, ensure_ascii=False, separators=(",", ":"))])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks", type=Path, help="screening_tasks.jsonl path")
    parser.add_argument("-o", "--output", type=Path, default=Path("submission.csv"))
    args = parser.parse_args()

    tasks = load_jsonl(args.tasks)
    payload = run_harness(tasks)
    validate(payload, tasks)
    write_submission(payload, args.output)
    print(f"wrote {args.output} ({len(payload['answers'])} answers)")


if __name__ == "__main__":
    main()
