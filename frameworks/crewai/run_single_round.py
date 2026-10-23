"""
Testira JEDNU rundu interakcije end-to-end kroz CrewAI
implementaciju -- identično po funkciji kao
frameworks/langgraph/run_single_round.py, samo uvozi LlamaIndex agenta.

Pokretanje (iz korijena projekta):
    py frameworks/crewai/run_single_round.py --profile common_errors --task-title "Predznak broja" --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import requests

from common import task_repo
from common.contract import AgentInput, StudentMasteryState, SubmissionResult, TestCaseResult
from frameworks.crewai.agent import run_agent

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "simulator")))
from student_simulator import fetch_profile, generate_submission  # noqa: E402

SANDBOX_URL = os.environ.get("ELT_SANDBOX_URL", "http://localhost:8090")


def _run_against_sandbox(code: str, task: dict) -> SubmissionResult:
    resp = requests.post(
        f"{SANDBOX_URL}/execute",
        json={"code": code, "test_cases": task["test_cases"], "entry_point": task["entry_point"]},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return SubmissionResult(
        task_id=task["id"],
        submitted_code=code,
        test_results=[TestCaseResult(**r) for r in data["results"]],
        pass_count=data["pass_count"],
        total_count=data["total_count"],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=["fast_accurate", "common_errors", "slow_unsure"])
    parser.add_argument("--task-title", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args()

    conn = task_repo.get_connection()
    try:
        profile = fetch_profile(conn, args.profile)
        task = task_repo.fetch_task_by_title(conn, args.task_title)
    finally:
        conn.close()

    simulated = generate_submission(profile, task, args.attempt, args.seed)
    print("=== SIMULIRANI PODNESAK ===")
    print(f"Namjeravana greška: {simulated.intended_error_code}")

    if simulated.needs_clarification:
        print(f"Student traži pojašnjenje: {simulated.clarification_text}")
        return

    submission_result = _run_against_sandbox(simulated.submitted_code, task)
    print(f"Test rezultat: {submission_result.pass_count}/{submission_result.total_count} prošlo")

    agent_input = AgentInput(
        session_id="test-session",
        framework_code="crewai",
        student_profile_code=args.profile,
        current_task_id=task["id"],
        submission=submission_result,
        mastery_state=[StudentMasteryState(concept_code=task["concept_code"], mastery=0.0, attempts=0)],
        step_index=args.attempt,
    )

    output = run_agent(agent_input, task, attempts_on_current_task=args.attempt - 1)

    print("\n=== ODGOVOR AGENTA (CrewAI) ===")
    print(json.dumps(output.model_dump(), indent=2, ensure_ascii=False, default=str))

    print("\n=== PROVJERA GROUND TRUTH vs DIJAGNOZA ===")
    print(f"Simulator ubacio: {simulated.intended_error_code}")
    print(f"Agent dijagnosticirao: {output.detected_error_code}")
    print(f"Podudara se: {simulated.intended_error_code == output.detected_error_code}")


if __name__ == "__main__":
    main()