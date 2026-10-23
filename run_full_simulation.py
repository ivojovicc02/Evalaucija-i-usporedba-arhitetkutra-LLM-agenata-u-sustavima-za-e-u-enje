"""
PUNA SIMULACIJA -- 4 frameworka x 3 profila studenata, svaki kroz punu
"sesiju" (od prvog zadatka do COMPLETE ili sigurnosnog limita koraka),
uz logovanje SVAKE interakcije u `interaction_logs` tabelu.

Ovo je glavna skripta za prikupljanje podataka za poglavlje 5
(Evaluacija i rezultati) diplomskog rada.

Napomena o seedu: isti --seed se koristi za SVE frameworke, čime je RNG
u simulatoru (koji tip pokušaja i koja greška se bira) deterministički
IDENTIČAN kroz sve 4 arhitekture za isti profil/zadatak/pokušaj -- razlike
u ishodu dolaze iz same orkestracije/LLM odgovora, ne iz različitog
"scenarija" studenta. Sam TEKST LLM-generisanog koda i dalje ima svoju
varijabilnost (vidi napomenu u README.md o determinizmu simulatora).

Pokretanje (iz korijena projekta):
    py run_full_simulation.py --seed 42
    py run_full_simulation.py --seed 42 --frameworks langgraph,crewai --profiles common_errors
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "simulator")))

import requests

from common import task_repo
from common.contract import AgentInput, StudentMasteryState, SubmissionResult, TestCaseResult
from student_simulator import fetch_profile, generate_submission  # noqa: E402

SANDBOX_URL = os.environ.get("ELT_SANDBOX_URL", "http://localhost:8090")
MAX_STEPS_PER_SESSION = int(os.environ.get("ELT_MAX_STEPS", "30"))

ALL_FRAMEWORKS = ["langgraph", "llamaindex", "crewai", "openai_sdk"]
ALL_PROFILES = ["fast_accurate", "common_errors", "slow_unsure"]


def _load_agent_runner(framework_code: str):
    if framework_code == "langgraph":
        from frameworks.langgraph.agent import run_agent
    elif framework_code == "llamaindex":
        from frameworks.llamaindex.agent import run_agent
    elif framework_code == "crewai":
        from frameworks.crewai.agent import run_agent
    elif framework_code == "openai_sdk":
        from frameworks.openai_sdk.agent import run_agent
    else:
        raise ValueError(f"Nepoznat framework: {framework_code}")
    return run_agent


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


def _log_interaction(conn, **kwargs) -> None:
    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join(["%s"] * len(kwargs))
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO interaction_logs ({columns}) VALUES ({placeholders});", list(kwargs.values()))
    conn.commit()


def _fetch_all_concepts(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, code, order_index FROM concepts ORDER BY order_index;")
        return cur.fetchall()


def _fetch_first_task(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.code AS concept_code, c.order_index AS concept_order_index
            FROM tasks t JOIN concepts c ON t.concept_id = c.id
            WHERE c.order_index = 1 AND t.difficulty = 1 LIMIT 1;
            """
        )
        return cur.fetchone()


def run_session(run_agent, framework_code: str, profile: dict, seed: int) -> dict:
    """Vodi jednu punu sesiju (jedan profil kroz jedan framework). Vraća sažetak."""
    conn = task_repo.get_connection()
    session_id = str(uuid.uuid4())
    stats = {"steps": 0, "correct": 0, "incorrect": 0, "errors": 0}

    try:
        concepts = _fetch_all_concepts(conn)
        mastery_state = [StudentMasteryState(concept_code=c["code"], mastery=0.0, attempts=0) for c in concepts]
        current_task = _fetch_first_task(conn)
        attempts_on_task = 0
        attempt_counter_per_task: dict[int, int] = {}

        # Prvi korak -- agent samo predstavlja prvi zadatak (submission=None)
        step_index = 1
        agent_input = AgentInput(
            session_id=session_id, framework_code=framework_code, student_profile_code=profile["code"],
            current_task_id=current_task["id"], submission=None, mastery_state=mastery_state, step_index=step_index,
        )
        try:
            output = run_agent(agent_input, current_task, attempts_on_current_task=0)
            _log_interaction(
                conn, session_id=session_id, framework_code=framework_code, student_profile_id=profile["id"],
                task_id=current_task["id"], step_index=step_index, submitted_code=None,
                test_pass_count=None, test_total_count=None, is_correct=None,
                detected_error_code=None, actual_error_code=None, agent_feedback_text=output.feedback_text,
                next_action=output.next_action.value, mastery_before=0.0, mastery_after=0.0,
                llm_call_count=output.llm_call_count, input_tokens=output.input_tokens,
                output_tokens=output.output_tokens, latency_ms=output.latency_ms,
                error_occurred=False, error_message=None,
            )
        except Exception as e:
            print(f"    [GREŠKA na uvodnom koraku] {e}")
            stats["errors"] += 1
            return stats

        while step_index < MAX_STEPS_PER_SESSION:
            step_index += 1
            stats["steps"] += 1

            attempt_number = attempt_counter_per_task.get(current_task["id"], 0) + 1
            attempt_counter_per_task[current_task["id"]] = attempt_number

            try:
                simulated = generate_submission(profile, current_task, attempt_number, seed)

                if simulated.needs_clarification:
                    print(f"    [Korak {step_index}] {current_task['title']}: student traži pojašnjenje, preskačem")
                    continue

                submission_result = _run_against_sandbox(simulated.submitted_code, current_task)
                is_correct = submission_result.is_correct
                stats["correct" if is_correct else "incorrect"] += 1

                mastery_before = next(m.mastery for m in mastery_state if m.concept_code == current_task["concept_code"])

                agent_input = AgentInput(
                    session_id=session_id, framework_code=framework_code, student_profile_code=profile["code"],
                    current_task_id=current_task["id"], submission=submission_result,
                    mastery_state=mastery_state, step_index=step_index,
                )
                output = run_agent(agent_input, current_task, attempts_on_current_task=attempt_number - 1)
                mastery_state = output.updated_mastery
                mastery_after = next(m.mastery for m in mastery_state if m.concept_code == current_task["concept_code"])

                _log_interaction(
                    conn, session_id=session_id, framework_code=framework_code, student_profile_id=profile["id"],
                    task_id=current_task["id"], step_index=step_index, submitted_code=simulated.submitted_code,
                    test_pass_count=submission_result.pass_count, test_total_count=submission_result.total_count,
                    is_correct=is_correct, detected_error_code=output.detected_error_code,
                    actual_error_code=simulated.intended_error_code, agent_feedback_text=output.feedback_text,
                    next_action=output.next_action.value, mastery_before=mastery_before, mastery_after=mastery_after,
                    llm_call_count=output.llm_call_count, input_tokens=output.input_tokens,
                    output_tokens=output.output_tokens, latency_ms=output.latency_ms,
                    error_occurred=False, error_message=None,
                )

                print(
                    f"    [Korak {step_index}] {current_task['title']}: "
                    f"{'TAČNO' if is_correct else 'netačno'} -> {output.next_action.value}"
                )

                if output.next_action.value == "complete":
                    break
                elif output.next_action.value == "retry":
                    pass  # ostaje isti current_task
                else:  # advance ili easier
                    current_task = task_repo.fetch_task(conn, output.next_task_id)

            except Exception as e:
                print(f"    [GREŠKA na koraku {step_index}] {e}")
                stats["errors"] += 1
                try:
                    _log_interaction(
                        conn, session_id=session_id, framework_code=framework_code, student_profile_id=profile["id"],
                        task_id=current_task["id"], step_index=step_index, submitted_code=None,
                        test_pass_count=None, test_total_count=None, is_correct=None,
                        detected_error_code=None, actual_error_code=None, agent_feedback_text=None,
                        next_action=None, mastery_before=None, mastery_after=None,
                        llm_call_count=0, input_tokens=0, output_tokens=0, latency_ms=0,
                        error_occurred=True, error_message=str(e)[:500],
                    )
                except Exception:
                    pass
                # nastavi sesiju umjesto da je potpuno prekineš zbog jedne greške
                continue

    finally:
        conn.close()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frameworks", default=",".join(ALL_FRAMEWORKS))
    parser.add_argument("--profiles", default=",".join(ALL_PROFILES))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    frameworks = args.frameworks.split(",")
    profile_codes = args.profiles.split(",")

    conn = task_repo.get_connection()
    try:
        profiles = {p: fetch_profile(conn, p) for p in profile_codes}
    finally:
        conn.close()

    overall_start = time.monotonic()
    for framework_code in frameworks:
        print(f"\n{'=' * 60}\nFRAMEWORK: {framework_code}\n{'=' * 60}")
        try:
            run_agent = _load_agent_runner(framework_code)
        except Exception as e:
            print(f"  [PRESKAČEM framework '{framework_code}'] Ne mogu učitati agenta: {e}")
            continue

        for profile_code in profile_codes:
            profile = profiles[profile_code]
            print(f"\n  --- Profil: {profile_code} ---")
            session_start = time.monotonic()
            stats = run_session(run_agent, framework_code, profile, args.seed)
            elapsed = time.monotonic() - session_start
            print(
                f"  Sesija gotova za {elapsed:.1f}s -- koraka: {stats['steps']}, "
                f"tačno: {stats['correct']}, netačno: {stats['incorrect']}, greške: {stats['errors']}"
            )

    total_elapsed = time.monotonic() - overall_start
    print(f"\n{'=' * 60}\nPUNA SIMULACIJA ZAVRŠENA za {total_elapsed / 60:.1f} minuta.\n{'=' * 60}")


if __name__ == "__main__":
    main()