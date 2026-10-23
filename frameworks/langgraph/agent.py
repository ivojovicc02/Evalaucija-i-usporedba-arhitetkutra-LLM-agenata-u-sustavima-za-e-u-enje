"""
LangGraph implementacija tutor agenta.

Orkestracija je eksplicitan graf stanja (StateGraph): svaki čvor je jasno
definisana funkcija, ivice određuju redoslijed. Ovo je namjerno drugačiji
stil orkestracije od CrewAI (role-based) ili LlamaIndex Workflows
(event-driven) -- upravo tu razliku poglavlje 5 mjeri.

LLM pozivi i pedagoška pravila dolaze iz common/ (llm_client, policy,
task_repo) -- IDENTIČNI u sve 4 implementacije. Ovaj fajl sadrži SAMO
LangGraph-specifičnu orkestraciju.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, TypedDict

# Omogući `from common.xxx import ...` bez obzira odakle se skripta pokreće
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from langgraph.graph import StateGraph, END

from common.contract import AgentInput, AgentOutput, NextAction, StudentMasteryState
from common.llm_client import call_llm
from common import policy
from common import task_repo


class GraphState(TypedDict):
    agent_input: AgentInput
    task: dict
    attempts_on_current_task: int

    is_correct: bool
    detected_error_code: Optional[str]
    next_action: str
    next_task_id: Optional[int]
    updated_mastery: list
    feedback_text: str

    llm_call_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: int


def _track(state: GraphState, result) -> None:
    state["llm_call_count"] += 1
    state["input_tokens"] += result.input_tokens
    state["output_tokens"] += result.output_tokens
    state["latency_ms"] += result.latency_ms


def node_diagnose(state: GraphState) -> GraphState:
    submission = state["agent_input"].submission
    task = state["task"]

    if submission is None:
        state["is_correct"] = False
        state["detected_error_code"] = None
        return state

    is_correct = submission.is_correct
    state["is_correct"] = is_correct

    if is_correct or not task.get("common_errors"):
        state["detected_error_code"] = None
        return state

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
    _track(state, result)

    detected = result.text.strip().strip("`").lower()
    valid_codes = {e["error_code"] for e in task["common_errors"]}
    print(f"    [DEBUG] LLM vratio: {detected!r}, validni kodovi: {valid_codes}")
    state["detected_error_code"] = detected if detected in valid_codes else None
    return state


def node_decide(state: GraphState) -> GraphState:
    is_correct = state["is_correct"]
    action = policy.decide_next_action(is_correct, state["attempts_on_current_task"])
    state["next_action"] = action

    concept_code = state["task"]["concept_code"]
    updated = []
    for m in state["agent_input"].mastery_state:
        if m.concept_code == concept_code:
            new_mastery = policy.update_mastery(m.mastery, is_correct)
            updated.append(StudentMasteryState(concept_code=m.concept_code, mastery=new_mastery, attempts=m.attempts + 1))
        else:
            updated.append(m)
    state["updated_mastery"] = updated
    return state


def node_resolve_next_task(state: GraphState) -> GraphState:
    conn = task_repo.get_connection()
    try:
        action = state["next_action"]
        if action == "retry":
            state["next_task_id"] = state["task"]["id"]
        elif action == "easier":
            nxt = task_repo.resolve_easier_task(conn, state["task"])
            state["next_task_id"] = nxt["id"] if nxt else None
        else:  # advance
            nxt = task_repo.resolve_advance_task(conn, state["task"])
            state["next_task_id"] = nxt["id"] if nxt else None
            if nxt is None:
                state["next_action"] = "complete"
    finally:
        conn.close()
    return state


def node_generate_feedback(state: GraphState) -> GraphState:
    task = state["task"]
    is_correct = state["is_correct"]
    submission = state["agent_input"].submission

    if submission is None:
        state["feedback_text"] = f"Evo tvog prvog zadatka: {task['title']}. Sretno!"
        return state

    if is_correct:
        system_prompt = (
            "Ti si prijateljski tutor programiranja. Student je TAČNO riješio zadatak. "
            "Napiši kratku (1-2 rečenice) pohvalu na bosanskom/hrvatskom/srpskom jeziku."
        )
        user_prompt = f"Zadatak: {task['title']}. Student je uspio iz {state['attempts_on_current_task'] + 1}. pokušaja."
    else:
        error_desc = "nepoznatu grešku"
        if state["detected_error_code"]:
            match = next((e for e in task["common_errors"] if e["error_code"] == state["detected_error_code"]), None)
            if match:
                error_desc = match["description"]
        system_prompt = (
            "Ti si prijateljski tutor programiranja. Student NIJE tačno riješio zadatak. "
            "NE DAJI rješenje. Daj kratku (1-2 rečenice), ohrabrujuću podsjetnicu koja "
            "usmjerava studenta ka ispravci, na bosanskom/hrvatskom/srpskom jeziku."
        )
        user_prompt = f"Zadatak: {task['title']}. Vjerovatna greška: {error_desc}."

    result = call_llm(system_prompt, user_prompt, temperature=0.5, max_tokens=1000)
    _track(state, result)
    state["feedback_text"] = result.text.strip()
    return state


def _build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("diagnose", node_diagnose)
    graph.add_node("decide", node_decide)
    graph.add_node("resolve_next_task", node_resolve_next_task)
    graph.add_node("feedback", node_generate_feedback)

    graph.set_entry_point("diagnose")
    graph.add_edge("diagnose", "decide")
    graph.add_edge("decide", "resolve_next_task")
    graph.add_edge("resolve_next_task", "feedback")
    graph.add_edge("feedback", END)
    return graph.compile()


_COMPILED_GRAPH = _build_graph()


def run_agent(agent_input: AgentInput, task: dict, attempts_on_current_task: int) -> AgentOutput:
    """Javni ulaz u LangGraph agenta -- prima/vraća isključivo common/contract.py tipove."""
    initial_state: GraphState = {
        "agent_input": agent_input,
        "task": task,
        "attempts_on_current_task": attempts_on_current_task,
        "is_correct": False,
        "detected_error_code": None,
        "next_action": "retry",
        "next_task_id": None,
        "updated_mastery": agent_input.mastery_state,
        "feedback_text": "",
        "llm_call_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "latency_ms": 0,
    }

    final_state = _COMPILED_GRAPH.invoke(initial_state)

    action_map = {
        "advance": NextAction.ADVANCE,
        "retry": NextAction.RETRY,
        "easier": NextAction.EASIER,
        "complete": NextAction.COMPLETE,
    }

    return AgentOutput(
        next_action=action_map[final_state["next_action"]],
        next_task_id=final_state["next_task_id"],
        feedback_text=final_state["feedback_text"],
        detected_error_code=final_state["detected_error_code"],
        updated_mastery=final_state["updated_mastery"],
        llm_call_count=final_state["llm_call_count"],
        input_tokens=final_state["input_tokens"],
        output_tokens=final_state["output_tokens"],
        latency_ms=final_state["latency_ms"],
    )