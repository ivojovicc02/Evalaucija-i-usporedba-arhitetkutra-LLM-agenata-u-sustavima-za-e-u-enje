"""
CrewAI implementacija tutor agenta.

Orkestracija je role-based: dva agenta sa definisanim ulogama
("Dijagnostičar grešaka" i "Tutor za povratnu informaciju") izvršavaju
sekvencu zadataka (Task) unutar jednog Crew-a, umjesto eksplicitnog grafa
(LangGraph) ili lanca eventa (LlamaIndex Workflows) -- upravo ta razlika
u stilu orkestracije je ono što poglavlje 5 mjeri.

Pedagoška odluka (advance/retry/easier) i update mastery-ja OSTAJU
deterministički, izvan CrewAI-ja (common/policy.py) -- isto kao u druge
dvije implementacije -- jer to nije nešto što bi trebalo prepustiti LLM
"rasuđivanju" radi fer, reproducibilnog poređenja.

Za razliku od LangGraph/LlamaIndex implementacije (koje koriste
common/llm_client.py direktno), ovdje LLM pozive radi SAM CrewAI kroz
svoj `LLM` wrapper (litellm ispod haube) -- ovo je namjerno, jer je to
autentičan način rada s CrewAI-jem, i CrewAI sam prati broj poziva i
tokena kroz `crew.usage_metrics`, što koristimo za iste metrike kao i
kod druge dvije implementacije.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from crewai import Agent, Task, Crew, Process, LLM
import crewai.llms.cache as _crewai_cache
_crewai_cache.mark_cache_breakpoint = lambda msg: msg

from common.contract import AgentInput, AgentOutput, NextAction, StudentMasteryState
from common import policy
from common import task_repo

_LLM = LLM(model=f"groq/{os.environ.get('ELT_AGENT_MODEL', 'llama-3.1-8b-instant')}")
_cumulative_usage = {"successful_requests": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _build_diagnosis_agent() -> Agent:
    return Agent(
        role="Dijagnostičar grešaka u kodu",
        goal="Precizno prepoznati koji tip greške sadrži studentski Python kod, iz zadate liste mogućih grešaka.",
        backstory=(
            "Iskusan si asistent za nastavu programiranja koji je vidio hiljade "
            "tipičnih grešaka početnika i zna ih brzo prepoznati."
        ),
        llm=_LLM,
        verbose=False,
    )


def _build_feedback_agent() -> Agent:
    return Agent(
        role="Tutor za povratnu informaciju",
        goal="Dati kratku, ohrabrujuću povratnu informaciju studentu, bez otkrivanja gotovog rješenja.",
        backstory=(
            "Prijateljski nastavnik programiranja koji vjeruje da studenti uče "
            "najbolje kad ih se usmjeri, a ne kad im se odmah da gotov odgovor."
        ),
        llm=_LLM,
        verbose=False,
    )


def _diagnosis_task(agent: Agent, submission_code: str, common_errors: list[dict]) -> Task:
    error_list_text = "\n".join(f"- {e['error_code']}: {e['description']}" for e in common_errors)
    return Task(
        description=(
            f"Analiziraj sljedeći studentski Python kod:\n\n{submission_code}\n\n"
            f"Mogući tipovi grešaka:\n{error_list_text}\n\n"
            "Odgovori SAMO tačnim error_code iz liste koji najbolje odgovara koju "
            "od navedenih grešaka kod sadrži, ili riječju 'unknown' ako se ne "
            "poklapa nijedan. Ne piši ništa drugo."
        ),
        expected_output="Tačan error_code (jedna riječ, bez objašnjenja) ili 'unknown'.",
        agent=agent,
    )


def _feedback_task(agent: Agent, task: dict, is_correct: bool, attempts: int, diagnosis_task: Optional[Task]) -> Task:
    if is_correct:
        description = (
            f"Student je TAČNO riješio zadatak '{task['title']}' iz {attempts + 1}. pokušaja. "
            "Napiši kratku (1-2 rečenice) pohvalu na bosanskom/hrvatskom/srpskom jeziku."
        )
        context = []
    else:
        description = (
            f"Student NIJE tačno riješio zadatak '{task['title']}'. Pogledaj dijagnozu greške "
            "iz prethodnog zadatka (dobićeš je kao kontekst). NE DAJI gotovo rješenje. Daj kratku "
            "(1-2 rečenice), ohrabrujuću podsjetnicu koja usmjerava studenta ka ispravci, na "
            "bosanskom/hrvatskom/srpskom jeziku."
        )
        context = [diagnosis_task] if diagnosis_task else []
    return Task(
        description=description,
        expected_output="Kratka povratna informacija studentu (1-2 rečenice).",
        agent=agent,
        context=context,
    )


def run_agent(agent_input: AgentInput, task: dict, attempts_on_current_task: int) -> AgentOutput:
    """Javni ulaz u CrewAI agenta -- prima/vraća isključivo common/contract.py tipove."""
    submission = agent_input.submission

    llm_call_count = 0
    input_tokens = 0
    output_tokens = 0
    latency_ms = 0
    detected_error_code: Optional[str] = None
    feedback_text: str

    if submission is None:
        feedback_text = f"Evo tvog prvog zadatka: {task['title']}. Sretno!"
        is_correct = False
    else:
        is_correct = submission.is_correct
        diagnosis_agent = _build_diagnosis_agent()
        feedback_agent = _build_feedback_agent()

        agents = []
        tasks = []
        diagnosis_task_obj: Optional[Task] = None

        if not is_correct and task.get("common_errors"):
            diagnosis_task_obj = _diagnosis_task(diagnosis_agent, submission.submitted_code, task["common_errors"])
            agents.append(diagnosis_agent)
            tasks.append(diagnosis_task_obj)

        fb_task = _feedback_task(feedback_agent, task, is_correct, attempts_on_current_task, diagnosis_task_obj)
        agents.append(feedback_agent)
        tasks.append(fb_task)

        crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)

        
        max_retries = 5
        for attempt in range(max_retries):
            start = time.monotonic()
            try:
                crew.kickoff()
                break
            except Exception as e:
                if "rate_limit_exceeded" in str(e) and attempt < max_retries - 1:
                    wait_seconds = 20 * (attempt + 1)
                    print(f"[RATE LIMIT - CrewAI] Čekam {wait_seconds}s prije ponovnog pokušaja ({attempt + 1}/{max_retries})...")
                    time.sleep(wait_seconds)
                    continue
                raise
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = crew.usage_metrics
        total_requests = getattr(usage, "successful_requests", 0)
        total_input = getattr(usage, "prompt_tokens", 0)
        total_output = getattr(usage, "completion_tokens", 0)

        # crew.usage_metrics je kumulativan kroz cijeli proces (dijeljeni _LLM objekat),
        # pa računamo RAZLIKU od zadnjeg mjerenja da dobijemo brojeve SAMO za ovu interakciju.
        llm_call_count = total_requests - _cumulative_usage["successful_requests"]
        input_tokens = total_input - _cumulative_usage["prompt_tokens"]
        output_tokens = total_output - _cumulative_usage["completion_tokens"]
        _cumulative_usage["successful_requests"] = total_requests
        _cumulative_usage["prompt_tokens"] = total_input
        _cumulative_usage["completion_tokens"] = total_output

        if diagnosis_task_obj is not None:
            raw = (diagnosis_task_obj.output.raw or "").strip().strip("`").lower()
            valid_codes = {e["error_code"] for e in task["common_errors"]}
            detected_error_code = raw if raw in valid_codes else None

        feedback_text = (fb_task.output.raw or "").strip()

    action = policy.decide_next_action(is_correct, attempts_on_current_task)

    concept_code = task["concept_code"]
    updated_mastery = []
    for m in agent_input.mastery_state:
        if m.concept_code == concept_code:
            new_mastery = policy.update_mastery(m.mastery, is_correct)
            updated_mastery.append(StudentMasteryState(concept_code=m.concept_code, mastery=new_mastery, attempts=m.attempts + 1))
        else:
            updated_mastery.append(m)

    conn = task_repo.get_connection()
    try:
        if action == "retry":
            next_task_id = task["id"]
        elif action == "easier":
            nxt = task_repo.resolve_easier_task(conn, task)
            next_task_id = nxt["id"] if nxt else None
        else:  # advance
            nxt = task_repo.resolve_advance_task(conn, task)
            next_task_id = nxt["id"] if nxt else None
            if nxt is None:
                action = "complete"
    finally:
        conn.close()

    action_map = {
        "advance": NextAction.ADVANCE,
        "retry": NextAction.RETRY,
        "easier": NextAction.EASIER,
        "complete": NextAction.COMPLETE,
    }

    return AgentOutput(
        next_action=action_map[action],
        next_task_id=next_task_id,
        feedback_text=feedback_text,
        detected_error_code=detected_error_code,
        updated_mastery=updated_mastery,
        llm_call_count=llm_call_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )