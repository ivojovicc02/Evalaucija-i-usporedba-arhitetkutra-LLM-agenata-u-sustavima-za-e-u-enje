"""
Zajednički "agent contract" -- isti ulaz/izlaz koji MORA poštovati
implementacija u svakom od 4 frameworka (LangGraph, CrewAI,
LlamaIndex Workflows, OpenAI Agents SDK).

Svrha: bez ovoga bi svaka implementacija mogla raditi malo drugačiju
verziju zadatka, čime bi poređenje metrika (poglavlje 5 rada) postalo
nevaljano. Sve 4 implementacije uvoze OVE modele i njima omotavaju
svoju internu (framework-specifičnu) logiku.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class NextAction(str, Enum):
    ADVANCE = "advance"     # tačno -> sljedeći (teži) zadatak
    RETRY = "retry"         # netačno -> pokušaj ponovo isti zadatak
    EASIER = "easier"       # netačno više puta -> lakši zadatak
    HARDER = "harder"       # tačno više puta zaredom -> preskoči nivo
    COMPLETE = "complete"   # sav gradivo savladano


class TestCaseResult(BaseModel):
    passed: bool
    actual_output: Optional[str] = None
    error: Optional[str] = None


class SubmissionResult(BaseModel):
    """Rezultat izvršavanja studentovog koda u sandbox-u (ulaz agentu)."""
    task_id: int
    submitted_code: str
    test_results: list[TestCaseResult]
    pass_count: int
    total_count: int

    @property
    def is_correct(self) -> bool:
        return self.pass_count == self.total_count


class StudentMasteryState(BaseModel):
    """Trenutno stanje studenta po konceptu -- ulaz agentu."""
    concept_code: str
    mastery: float = Field(ge=0.0, le=1.0)
    attempts: int = 0


class AgentInput(BaseModel):
    """STANDARDNI ulaz za jedan 'krug' interakcije, identičan u sva 4 frameworka."""
    session_id: str
    framework_code: str  # 'langgraph' | 'crewai' | 'llamaindex' | 'openai_sdk'
    student_profile_code: str
    current_task_id: int
    submission: Optional[SubmissionResult] = None  # None na prvom koraku sesije
    mastery_state: list[StudentMasteryState]
    step_index: int


class AgentOutput(BaseModel):
    """STANDARDNI izlaz za jedan 'krug' interakcije, identičan u sva 4 frameworka."""
    next_action: NextAction
    next_task_id: Optional[int] = None
    feedback_text: str
    detected_error_code: Optional[str] = None
    updated_mastery: list[StudentMasteryState]

    # metrike koje SVAKA implementacija mora sama popuniti radi evaluacije
    llm_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0