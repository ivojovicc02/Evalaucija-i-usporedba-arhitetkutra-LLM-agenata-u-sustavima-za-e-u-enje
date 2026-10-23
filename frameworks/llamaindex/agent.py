"""
LlamaIndex Workflows implementacija tutor agenta.

Orkestracija je event-driven: koraci (@step) primaju tipiziran Event i
emituju sljedeći Event, umjesto eksplicitnog grafa čvorova/ivica kao kod
LangGraph-a. Isti tok (dijagnoza -> odluka -> sljedeći zadatak -> feedback)
je ovdje izražen kroz lanac Event tipova -- upravo ta razlika u stilu
orkestracije je ono što poglavlje 5 mjeri.

LLM pozivi i pedagoška pravila dolaze iz common/ (llm_client, policy,
task_repo) -- IDENTIČNI kao u LangGraph implementaciji. Ovaj fajl sadrži
SAMO LlamaIndex-specifičnu orkestraciju.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from workflows import Workflow, step
from workflows.events import StartEvent, StopEvent, Event

from common.contract import AgentInput, AgentOutput, NextAction, StudentMasteryState
from common.llm_client import call_llm
from common import policy
from common import task_repo


# --- Event tipovi -- svaki nosi tačno ono što sljedeći korak treba ---

class DiagnosisEvent(Event):
    model_config = {"arbitrary_types_allowed": True}
    agent_input: AgentInput
    task: dict
    attempts_on_current_task: int
    is_correct: bool
    detected_error_code: Optional[str]
    llm_call_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: int


class DecisionEvent(Event):
    model_config = {"arbitrary_types_allowed": True}
    agent_input: AgentInput
    task: dict
    is_correct: bool
    detected_error_code: Optional[str]
    next_action: str
    updated_mastery: list
    attempts_on_current_task: int
    llm_call_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: int


class NextTaskEvent(Event):
    model_config = {"arbitrary_types_allowed": True}
    agent_input: AgentInput
    task: dict
    is_correct: bool
    detected_error_code: Optional[str]
    next_action: str
    next_task_id: Optional[int]
    updated_mastery: list
    attempts_on_current_task: int
    llm_call_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: int


class TutorWorkflow(Workflow):

    @step
    async def diagnose(self, ev: StartEvent) -> DiagnosisEvent:
        agent_input: AgentInput = ev.get("agent_input")
        task: dict = ev.get("task")
        attempts_on_current_task: int = ev.get("attempts_on_current_task")

        submission = agent_input.submission
        llm_call_count, input_tokens, output_tokens, latency_ms = 0, 0, 0, 0

        if submission is None:
            return DiagnosisEvent(
                agent_input=agent_input, task=task, attempts_on_current_task=attempts_on_current_task,
                is_correct=False, detected_error_code=None,
                llm_call_count=llm_call_count, input_tokens=input_tokens,
                output_tokens=output_tokens, latency_ms=latency_ms,
            )

        is_correct = submission.is_correct
        detected_error_code = None

        if not is_correct and task.get("common_errors"):
            error_list_text = "\n".join(
                f"- {e['error_code']}: {e['description']}" for e in task["common_errors"]
            )
            system_prompt = (
                "Ti si asistent koji dijagnosticira grešku u studentskom Python kodu. "
                "Dobićeš kod i listu mogućih tipova grešaka. Odgovori SAMO tačnim "
                "error_code iz liste koji najbolje odgovara, ili 'unknown' ako se "
                "ne poklapa nijedan. Ne objašnjavaj, samo vrati kod greške."
            )
            user_prompt = (
                f"Kod studenta:\n{submission.submitted_code}\n\n"
                f"Mogući tipovi grešaka:\n{error_list_text}\n\n"
                f"Koji error_code najbolje odgovara?"
            )
            result = call_llm(system_prompt, user_prompt, temperature=0.0, max_tokens=1000)
            llm_call_count += 1
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            latency_ms += result.latency_ms

            detected = result.text.strip().strip("`").lower()
            valid_codes = {e["error_code"] for e in task["common_errors"]}
            detected_error_code = detected if detected in valid_codes else None

        return DiagnosisEvent(
            agent_input=agent_input, task=task, attempts_on_current_task=attempts_on_current_task,
            is_correct=is_correct, detected_error_code=detected_error_code,
            llm_call_count=llm_call_count, input_tokens=input_tokens,
            output_tokens=output_tokens, latency_ms=latency_ms,
        )

    @step
    async def decide(self, ev: DiagnosisEvent) -> DecisionEvent:
        action = policy.decide_next_action(ev.is_correct, ev.attempts_on_current_task)

        concept_code = ev.task["concept_code"]
        updated = []
        for m in ev.agent_input.mastery_state:
            if m.concept_code == concept_code:
                new_mastery = policy.update_mastery(m.mastery, ev.is_correct)
                updated.append(StudentMasteryState(concept_code=m.concept_code, mastery=new_mastery, attempts=m.attempts + 1))
            else:
                updated.append(m)

        return DecisionEvent(
            agent_input=ev.agent_input, task=ev.task, is_correct=ev.is_correct,
            detected_error_code=ev.detected_error_code, next_action=action, updated_mastery=updated,
            attempts_on_current_task=ev.attempts_on_current_task,
            llm_call_count=ev.llm_call_count, input_tokens=ev.input_tokens,
            output_tokens=ev.output_tokens, latency_ms=ev.latency_ms,
        )

    @step
    async def resolve_next_task(self, ev: DecisionEvent) -> NextTaskEvent:
        conn = task_repo.get_connection()
        next_task_id: Optional[int]
        action = ev.next_action
        try:
            if action == "retry":
                next_task_id = ev.task["id"]
            elif action == "easier":
                nxt = task_repo.resolve_easier_task(conn, ev.task)
                next_task_id = nxt["id"] if nxt else None
            else:  # advance
                nxt = task_repo.resolve_advance_task(conn, ev.task)
                next_task_id = nxt["id"] if nxt else None
                if nxt is None:
                    action = "complete"
        finally:
            conn.close()

        return NextTaskEvent(
            agent_input=ev.agent_input, task=ev.task, is_correct=ev.is_correct,
            detected_error_code=ev.detected_error_code, next_action=action, next_task_id=next_task_id,
            updated_mastery=ev.updated_mastery, attempts_on_current_task=ev.attempts_on_current_task,
            llm_call_count=ev.llm_call_count, input_tokens=ev.input_tokens,
            output_tokens=ev.output_tokens, latency_ms=ev.latency_ms,
        )

    @step
    async def feedback(self, ev: NextTaskEvent) -> StopEvent:
        task = ev.task
        submission = ev.agent_input.submission
        llm_call_count, input_tokens, output_tokens, latency_ms = ev.llm_call_count, ev.input_tokens, ev.output_tokens, ev.latency_ms

        if submission is None:
            feedback_text = f"Evo tvog prvog zadatka: {task['title']}. Sretno!"
        elif ev.is_correct:
            system_prompt = (
                "Ti si prijateljski tutor programiranja. Student je TAČNO riješio zadatak. "
                "Napiši kratku (1-2 rečenice) pohvalu na bosanskom/hrvatskom/srpskom jeziku."
            )
            user_prompt = f"Zadatak: {task['title']}. Student je uspio iz {ev.attempts_on_current_task + 1}. pokušaja."
            result = call_llm(system_prompt, user_prompt, temperature=0.5, max_tokens=1000)
            llm_call_count += 1
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            latency_ms += result.latency_ms
            feedback_text = result.text.strip()
        else:
            error_desc = "nepoznatu grešku"
            if ev.detected_error_code:
                match = next((e for e in task["common_errors"] if e["error_code"] == ev.detected_error_code), None)
                if match:
                    error_desc = match["description"]
            system_prompt = (
                "Ti si prijateljski tutor programiranja. Student NIJE tačno riješio zadatak. "
                "NE DAJI rješenje. Daj kratku (1-2 rečenice), ohrabrujuću podsjetnicu koja "
                "usmjerava studenta ka ispravci, na bosanskom/hrvatskom/srpskom jeziku."
            )
            user_prompt = f"Zadatak: {task['title']}. Vjerovatna greška: {error_desc}."
            result = call_llm(system_prompt, user_prompt, temperature=0.5, max_tokens=1000)
            llm_call_count += 1
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            latency_ms += result.latency_ms
            feedback_text = result.text.strip()

        action_map = {
            "advance": NextAction.ADVANCE,
            "retry": NextAction.RETRY,
            "easier": NextAction.EASIER,
            "complete": NextAction.COMPLETE,
        }

        output = AgentOutput(
            next_action=action_map[ev.next_action],
            next_task_id=ev.next_task_id,
            feedback_text=feedback_text,
            detected_error_code=ev.detected_error_code,
            updated_mastery=ev.updated_mastery,
            llm_call_count=llm_call_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        return StopEvent(result=output)


async def _run_workflow(agent_input: AgentInput, task: dict, attempts_on_current_task: int) -> AgentOutput:
    workflow = TutorWorkflow(timeout=60, verbose=False)
    return await workflow.run(agent_input=agent_input, task=task, attempts_on_current_task=attempts_on_current_task)


def run_agent(agent_input: AgentInput, task: dict, attempts_on_current_task: int) -> AgentOutput:
    """Javni ulaz u LlamaIndex agenta -- prima/vraća isključivo common/contract.py tipove."""
    return asyncio.run(_run_workflow(agent_input, task, attempts_on_current_task))