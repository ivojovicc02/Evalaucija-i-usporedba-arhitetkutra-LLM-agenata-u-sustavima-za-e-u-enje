"""
Zajednički LLM klijent -- IDENTIČAN poziv modela koji koriste sva 4
framework implementacije (LangGraph, CrewAI, LlamaIndex, OpenAI Agents SDK).

Namjerno je izdvojen ovdje: ako bi svaka implementacija sama pozivala
Groq (ili neki drugi provajder) na svoj način, razlike u latenciji/broju
tokena bi mogle doći od sitnih razlika u HTTP pozivu, ne od same
orkestracije koju zapravo uspoređuješ. Ovako je varijabla stvarno samo
"framework", što ti treba za validno poređenje u poglavlju 5.

Provajder je Groq (besplatan tier, OpenAI-kompatibilan format).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

GROQ_API_KEY_ENV = "GROQ_API_KEY"
DEFAULT_MODEL = os.environ.get("ELT_AGENT_MODEL", "openai/gpt-oss-20b")


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 500) -> LLMResult:
    api_key = os.environ[GROQ_API_KEY_ENV]

    max_retries = 5
    for attempt in range(max_retries):
        start = time.monotonic()
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": DEFAULT_MODEL,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=30,
        )
        if resp.status_code == 429:
            wait_seconds = 15 * (attempt + 1)
            print(f"[RATE LIMIT] Čekam {wait_seconds}s ({attempt + 1}/{max_retries})...")
            time.sleep(wait_seconds)
            continue
        resp.raise_for_status()
        data = resp.json()
        latency_ms = int((time.monotonic() - start) * 1000)
        usage = data.get("usage", {})
        return LLMResult(
            text=data["choices"][0]["message"]["content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )

    raise RuntimeError("Groq API i dalje vraća 429 nakon svih pokušaja.")