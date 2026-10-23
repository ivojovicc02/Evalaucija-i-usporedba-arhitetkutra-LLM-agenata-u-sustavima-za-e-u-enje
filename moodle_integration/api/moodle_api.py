"""
Tanak API sloj koji izlaže LangGraph implementaciju tutor agenta kao
jednostavan "tekst-u-tekst" endpoint, pogodan za povezivanje s Moodle
AI Subsystem-om (provider plugin, vidi moodle_plugin/ folder).

Ovo NIJE zamjena za run_full_simulation.py -- ovdje agent radi u
"upitno-odgovornom" (Q&A) modu: prima pitanje/kod studenta u slobodnom
tekstu, i vraća generisan tekst. Puna adaptivna petlja (izbor sljedećeg
zadatka, mastery praćenje) i dalje živi u run_full_simulation.py i
koristi se za EKSPERIMENT; ovaj servis demonstrira PRAKTIČNU primjenjivost
istog agenta u realnom LMS okruženju.

Pokretanje:
    pip install fastapi uvicorn
    uvicorn moodle_integration.api.moodle_api:app --port 8100
"""

from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from pydantic import BaseModel

from common.llm_client import call_llm

app = FastAPI(title="ELT Agent -- Moodle AI Provider Bridge")


class GenerateTextRequest(BaseModel):
    prompttext: str  # Moodle AI Subsystem šalje prompt pod ovim imenom polja


class GenerateTextResponse(BaseModel):
    generatedcontent: str
    finishreason: str = "stop"


SYSTEM_PROMPT = (
    "Ti si AI tutor za programiranje u Pythonu, ugrađen u Moodle kurs. "
    "Odgovaraj kratko, jasno, na jeziku kojim ti se student obrati. "
    "Ako student pita za pomoć oko koda, NE DAJI gotovo rješenje -- "
    "usmjeri ga pitanjima i podsjetnicima, u duhu Sokratovog dijaloga."
)


@app.post("/generate", response_model=GenerateTextResponse)
def generate(req: GenerateTextRequest) -> GenerateTextResponse:
    """Generički endpoint koji Moodle provider plugin poziva za process_generate_text akciju."""
    result = call_llm(SYSTEM_PROMPT, req.prompttext, temperature=0.4, max_tokens=400)
    return GenerateTextResponse(generatedcontent=result.text)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
