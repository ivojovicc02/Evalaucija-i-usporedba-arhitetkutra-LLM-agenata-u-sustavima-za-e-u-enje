"""
OpenAI Agents SDK implementacija tutor agenta.

Orkestracija je minimalistička: dva jednostavna Agent objekta (dijagnoza,
feedback) pozvana direktno kroz Runner.run_sync(), bez eksplicitnog grafa
(LangGraph), lanca eventa (LlamaIndex) ili role-based Crew-a (CrewAI) --
samo direktni sekvencijalni Python pozivi. Ovo je namjerno najlakši/
najminimalniji stil orkestracije od sve 4 implementacije, i to je upravo
ono što poglavlje 5 mjeri.

VAŽNA NAPOMENA O PROVAJDERU: OpenAI Agents SDK je prvobitno građen oko
OpenAI modela. Da bi ostao besplatan (dosljedno s ostale 3 implementacije),
ovdje se koristi Groq preko njegovog OpenAI-kompatibilnog endpointa
(https://api.groq.com/openai/v1), uz OpenAIChatCompletionsModel klasu iz
SDK-a. Ovo JE zvanično podržan način korištenja SDK-a s trećim
provajderima, ali zahtijeva malo više "ručne" konfiguracije nego kod
čistog OpenAI korištenja -- vrijedi spomenuti kao nalaz o developer
experience razlikama u poglavlju 5/6.

Pedagoška odluka (advance/retry/easier) i mastery update ostaju
deterministički, izvan SDK-a (common/policy.py) -- isto kao u druge 3
implementacije.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Isključi OpenAI tracing (traži pravi OpenAI ključ) -- mora biti postavljeno
# PRIJE importa `agents` paketa.
os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
os.environ.setdefault("OPENAI_API_KEY", "not-needed-using-groq")

import openai
from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel

from common.contract import AgentInput, AgentOutput, NextAction, StudentMasteryState
from common import policy
from common import task_repo

_GROQ_MODEL_NAME = os.environ.get("ELT_AGENT_MODEL", "llama-3.1-8b-instant")
_groq_client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"],
)
_MODEL = OpenAIChatCompletionsModel(model=_GROQ_MODEL_NAME, openai_client=_groq_client)


def _build_diagnosis_agent() -> Agent:
    return Agent(
        name="ErrorDiagnostician",
        instructions=(
            "Ti si asistent koji dijagnosticira grešku u studentskom Python kodu. "
            "Dobićeš kod i listu mogućih tipova grešaka. Odgovori SAMO tačnim "
            "error_code iz liste koji najbolje odgovara, ili 'unknown' ako se "
            "ne poklapa nijedan. Ne objašnjavaj, samo vrati kod greške."
        ),
        model=_MODEL,
    )


def _build_feedback_agent() -> Agent:
    return Agent(
        name="FeedbackTutor",
        instructions=(
            "Ti si prijateljski tutor programiranja koji daje kratke (1-2 rečenice), "
            "ohrabrujuće povratne informacije studentima na bosanskom/hrvatskom/srpskom "
            "jeziku. Kad je odgovor netačan, NIKAD ne daješ gotovo rješenje, samo "
            "usmjeravaš ka ispravci."
        ),
        model=_MODEL,
    )


def _run_with_retry(agent: Agent, prompt: str, max_retries: int = 5):
    for attempt in range(max_retries):
        start = time.monotonic()
        try:
            result = Runner.run_sync(agent, prompt)
            latency_ms = int((time.monotonic() - start) * 1000)
            return result, latency_ms
        except openai.RateLimitError as e:
            if attempt >= max_retries - 1:
                raise
            wait_seconds = 20 * (attempt + 1)
            print(f"[RATE LIMIT - OpenAI SDK] Čekam {wait_seconds}s ({attempt + 1}/{max_retries})... ({e})")
            time.sleep(wait_seconds)
    raise RuntimeError("Nedostignut broj pokušaja.")


def _extract_usage(result) -> tuple[int, int]:
    """Pokuša izvući broj tokena iz RunResult-a; vraća (0, 0) ako nije dostupno."""
    input_tokens, output_tokens = 0, 0
    try:
        for raw in getattr(result, "raw_responses", []) or []:
            usage = getattr(raw, "usage", None)
            if usage:
                input_tokens += getattr(usage, "input_tokens", 0) or 0
                output_tokens += getattr(usage, "output_tokens", 0) or 0
    except Exception:
        pass
    return input_tokens, output_tokens


def run_agent(agent_input: AgentInput, task: dict, attempts_on_current_task: int) -> AgentOutput:
    """Javni ulaz u OpenAI Agents SDK agenta -- prima/vraća isključivo common/contract.py tipove."""
    submission = agent_input.submission

    llm_call_count = 0
    input_tokens = 0
    output_tokens = 0
    latency_ms = 0
    detected_error_code: Optional[str] = None

    if submission is None:
        feedback_text = f"Evo tvog prvog zadatka: {task['title']}. Sretno!"
        is_correct = False
    else:
        is_correct = submission.is_correct
        

        if not is_correct and task.get("common_errors"):
            error_list_text = "\n".join(
                f"- {e['error_code']}: {e['description']}" for e in task["common_errors"]
            )
            diagnosis_prompt = (
                f"Kod studenta:\n{submission.submitted_code}\n\n"
                f"Mogući tipovi grešaka:\n{error_list_text}\n\n"
                f"Koji error_code najbolje odgovara?"
            )
            result, call_latency = _run_with_retry(_build_diagnosis_agent(), diagnosis_prompt)
            latency_ms += call_latency
            llm_call_count += 1
            in_tok, out_tok = _extract_usage(result)
            input_tokens += in_tok
            output_tokens += out_tok

            detected = str(result.final_output).strip().strip("`").lower()
            valid_codes = {e["error_code"] for e in task["common_errors"]}
            detected_error_code = detected if detected in valid_codes else None

        if is_correct:
            feedback_prompt = (
                f"Student je TAČNO riješio zadatak '{task['title']}' iz "
                f"{attempts_on_current_task + 1}. pokušaja. Napiši kratku pohvalu."
            )
        else:
            error_desc = "nepoznatu grešku"
            if detected_error_code:
                match = next((e for e in task["common_errors"] if e["error_code"] == detected_error_code), None)
                if match:
                    error_desc = match["description"]
            feedback_prompt = (
                f"Student NIJE tačno riješio zadatak '{task['title']}'. Vjerovatna greška: "
                f"{error_desc}. Daj kratku, ohrabrujuću podsjetnicu, bez gotovog rješenja."
            )

        result, call_latency = _run_with_retry(_build_feedback_agent(), feedback_prompt)
        latency_ms += call_latency
        llm_call_count += 1  
        in_tok, out_tok = _extract_usage(result)
        input_tokens += in_tok
        output_tokens += out_tok
        feedback_text = str(result.final_output).strip()

        

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