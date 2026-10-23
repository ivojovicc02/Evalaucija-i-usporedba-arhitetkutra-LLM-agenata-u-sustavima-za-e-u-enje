"""
Smoke test -- brzo prolazi kroz SVIH 12 zadataka (jedan profil, jedan
pokušaj po zadatku) da uhvati task-specifične bugove PRIJE nego repliciramo
isti obrazac agenta na LlamaIndex/CrewAI/OpenAI SDK.

Ovo NIJE puna simulacija za rezultate rada (to dolazi kasnije, sa svim
profilima i logovanjem u interaction_logs) -- ovo je samo brza provjera
zdravlja sistema.

Pokretanje (iz korijena projekta):
    py frameworks/langgraph/smoke_test_all_tasks.py --profile common_errors --seed 42
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import requests

from common import task_repo
from common.contract import AgentInput, StudentMasteryState, SubmissionResult, TestCaseResult
from frameworks.langgraph.agent import run_agent

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
    parser.add_argument("--profile", default="common_errors", choices=["fast_accurate", "common_errors", "slow_unsure"])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    conn = task_repo.get_connection()
    try:
        profile = fetch_profile(conn, args.profile)
        with conn.cursor() as cur:
            cur.execute("SELECT id, title FROM tasks ORDER BY id;")
            all_tasks = cur.fetchall()
    finally:
        conn.close()

    print(f"Pronađeno {len(all_tasks)} zadataka. Testiram profil '{args.profile}', seed={args.seed}.\n")

    results = []
    for row in all_tasks:
        title = row["title"]
        conn = task_repo.get_connection()
        try:
            task = task_repo.fetch_task_by_title(conn, title)
        finally:
            conn.close()

        try:
            simulated = generate_submission(profile, task, attempt_number=1, seed=args.seed)

            if simulated.needs_clarification:
                print(f"[{title}] -> student traži pojašnjenje (clarify), preskačem provjeru")
                results.append((title, "CLARIFY", None, None))
                continue

            submission_result = _run_against_sandbox(simulated.submitted_code, task)

            agent_input = AgentInput(
                session_id="smoke-test",
                framework_code="langgraph",
                student_profile_code=args.profile,
                current_task_id=task["id"],
                submission=submission_result,
                mastery_state=[StudentMasteryState(concept_code=task["concept_code"], mastery=0.0, attempts=0)],
                step_index=1,
            )
            output = run_agent(agent_input, task, attempts_on_current_task=0)

            match = simulated.intended_error_code == output.detected_error_code
            status = "OK" if match else "MISMATCH"
            print(
                f"[{title}] testovi={submission_result.pass_count}/{submission_result.total_count} "
                f"akcija={output.next_action.value} greška_ubačena={simulated.intended_error_code} "
                f"greška_dijagnoza={output.detected_error_code} -> {status}"
            )
            results.append((title, status, simulated.intended_error_code, output.detected_error_code))

        except Exception as e:
            print(f"[{title}] EXCEPTION: {e}")
            results.append((title, "EXCEPTION", None, str(e)))

    print("\n=== SAŽETAK ===")
    ok = sum(1 for r in results if r[1] == "OK")
    mismatch = sum(1 for r in results if r[1] == "MISMATCH")
    clarify = sum(1 for r in results if r[1] == "CLARIFY")
    exc = sum(1 for r in results if r[1] == "EXCEPTION")
    print(f"OK: {ok}, MISMATCH: {mismatch}, CLARIFY: {clarify}, EXCEPTION: {exc} (od {len(results)} ukupno)")


if __name__ == "__main__":
    main()