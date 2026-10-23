"""
Simulator studenata za evaluaciju agentnih arhitektura.

Za dati (task, student_profile, attempt_number) generiše "podnesak"
studenta -- ili ispravan kod, ili kod s namjerno ubačenom tipičnom
greškom (iz common_errors liste tog zadatka), ili nejasan/nepotpun
odgovor (za profil 'slow_unsure').

Ponašanje je određeno s `behavior_spec` (JSONB) iz `student_profiles`
tabele -- isti profil se pušta kroz sva 4 frameworka, pa MORA biti
determinističan po (seed, framework, task, attempt) da bi poređenje
bilo fer. Zato se seed eksplicitno postavlja po sesiji.


    py simulator/student_simulator.py --profile common_errors --task-title "Predznak broja" --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

DB_HOST = os.environ.get("ELT_DB_HOST", "localhost")
DB_PORT = os.environ.get("ELT_DB_PORT", "5432")
DB_NAME = os.environ.get("ELT_DB_NAME", "elt_agents")
DB_USER = os.environ.get("ELT_DB_USER", "elt_admin")
DB_PASSWORD = os.environ.get("ELT_DB_PASSWORD", "change_me_locally")
SANDBOX_URL = os.environ.get("ELT_SANDBOX_URL", "http://localhost:8090")

SIMULATOR_MODEL = os.environ.get("ELT_SIMULATOR_MODEL", "openai/gpt-oss-20b")

def _call_llm(system_prompt: str, user_prompt: str, temperature: float) -> str:
    """Poziva Groq API (besplatan tier, OpenAI-kompatibilan format)."""
    import time

    api_key = os.environ["GROQ_API_KEY"]

    max_retries = 5
    for attempt in range(max_retries):
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": SIMULATOR_MODEL,
                "temperature": temperature,
                "max_tokens": 500,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=30,
        )
        if resp.status_code == 429:
            print(f"[RATE LIMIT DETALJI] {resp.text}")
            wait_seconds = 20 * (attempt + 1)
            print(f"[RATE LIMIT] Čekam {wait_seconds}s prije ponovnog pokušaja ({attempt+1}/{max_retries})...")
            time.sleep(wait_seconds)
            continue
        if resp.status_code >= 400:
            print(f"[GROQ API GREŠKA {resp.status_code}] {resp.text}")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    raise RuntimeError("Groq API i dalje vraća 429 nakon svih pokušaja.")

@dataclass
class SimulatedSubmission:
    task_id: int
    attempt_number: int
    needs_clarification: bool          # True ako student ne šalje kod nego traži pojašnjenje
    submitted_code: Optional[str]
    clarification_text: Optional[str]
    intended_error_code: Optional[str]  # ground truth -- koju grešku smo namjerno ubacili (None = tačno)
    raw_model_response: str


def _get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def fetch_profile(conn, profile_code: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM student_profiles WHERE code = %s;", (profile_code,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Nepoznat profil studenta: {profile_code}")
        return row


def fetch_task_by_title(conn, title: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM tasks WHERE title = %s;", (title,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Nepoznat zadatak: {title}")
        return row


def _decide_attempt_type(behavior: dict, rng: random.Random) -> str:
    """Vraća 'correct' | 'buggy' | 'clarify' na osnovu behavior_spec i RNG-a."""
    if behavior.get("gives_short_unclear_answers") and rng.random() < 0.25:
        return "clarify"
    if rng.random() < behavior.get("correctness_rate", 0.7):
        return "correct"
    return "buggy"


def _pick_common_error(task: dict, attempt_number: int, behavior: dict, rng: random.Random) -> Optional[dict]:
    errors = task.get("common_errors") or []
    if not errors or not behavior.get("makes_typical_errors"):
        return None
    if behavior.get("error_injection_mode") == "one_common_error_per_attempt":
        return errors[(attempt_number - 1) % len(errors)]
    return rng.choice(errors)


def _build_system_prompt(profile: dict, task: dict, attempt_type: str, chosen_error: Optional[dict]) -> str:
    base = (
        "Ti glumiš studenta koji uči programiranje u Pythonu. Ne objašnjavaj svoje "
        "rezonovanje, samo daj traženi izlaz. Ne spominji da si AI ili da simuliraš."
    )
    if attempt_type == "correct":
        return (
            base
            + " Napiši ISPRAVNO, radno rješenje zadatka. Vrati SAMO Python kod, "
            "bez markdown ograda, bez objašnjenja."
        )
    if attempt_type == "buggy":
        assert chosen_error is not None
        return (
            base
            + f" Napiši rješenje zadatka koje sadrži SLJEDEĆU tipičnu grešku: "
            f"{chosen_error['description']}. Kod treba izgledati kao iskren pokušaj "
            "studenta, ne karikatura. Vrati SAMO Python kod, bez markdown ograda, bez objašnjenja."
        )
    return (
        base
        + " Ne razumiješ dobro zadatak. Postavi KRATKO (1 rečenica), nejasno ili "
        "nesigurno potpitanje umjesto da daš kod -- npr. traži pojašnjenje granica "
        "ili što tačno treba da funkcija radi. Ne piši kod."
    )

def _code_actually_fails(code: str, task: dict) -> bool:
    """Provjerava kod protiv sandboxa. Vraća True ako bar jedan test PADNE
    (znači greška se stvarno manifestuje) -- False ako sve prođe (bug se nije uhvatio)."""
    try:
        resp = requests.post(
            f"{SANDBOX_URL}/execute",
            json={
                "code": code,
                "test_cases": task["test_cases"],
                "entry_point": task["entry_point"],
                "timeout_seconds": 3.0,
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        return not result["all_passed"]
    except requests.RequestException as e:
        print(f"[UPOZORENJE] Sandbox provjera nije uspjela ({e}), pretpostavljam da kod NIJE testiran.")
        return True  # ne blokiraj tok ako sandbox nije dostupan

def generate_submission(
    profile: dict,
    task: dict,
    attempt_number: int,
    seed: int,
) -> SimulatedSubmission:
    behavior = profile["behavior_spec"]
    rng = random.Random(f"{seed}-{task['id']}-{attempt_number}")

    attempt_type = _decide_attempt_type(behavior, rng)
    chosen_error = _pick_common_error(task, attempt_number, behavior, rng) if attempt_type == "buggy" else None
    if attempt_type == "buggy" and chosen_error is None:
        # profil ne pravi tipične greške (ili zadatak nema definisane) -> tretiraj kao tačan pokušaj
        attempt_type = "correct"

    user_prompt = (
        f"Zadatak: {task['title']}\n\n{task['prompt']}\n\n"
        f"Ime funkcije koju treba definisati: {task['entry_point']}\n\n"
        f"Starter kod:\n{task.get('starter_code') or ''}"
    )

    if attempt_type != "buggy":
        system_prompt = _build_system_prompt(profile, task, attempt_type, chosen_error)
        raw_text = _call_llm(system_prompt, user_prompt, temperature=0.2 if attempt_type == "correct" else 0.7)

        if attempt_type == "clarify":
            return SimulatedSubmission(
                task_id=task["id"], attempt_number=attempt_number, needs_clarification=True,
                submitted_code=None, clarification_text=raw_text.strip(),
                intended_error_code=None, raw_model_response=raw_text,
            )

        code = raw_text.strip().strip("`")
        if code.lower().startswith("python"):
            code = code[len("python"):].strip()
        return SimulatedSubmission(
            task_id=task["id"], attempt_number=attempt_number, needs_clarification=False,
            submitted_code=code, clarification_text=None,
            intended_error_code=None, raw_model_response=raw_text,
        )

    # attempt_type == "buggy" -- generiši, PA PROVJERI da greška zaista pada na testovima
    assert chosen_error is not None
    max_gen_attempts = 3
    for gen_attempt in range(max_gen_attempts):
        emphasis = "" if gen_attempt == 0 else " VAŽNO: prošli pokušaj je bio slučajno ispravan -- osiguraj da kod STVARNO ima ovu grešku i STVARNO daje pogrešan rezultat."
        system_prompt = _build_system_prompt(profile, task, attempt_type, chosen_error) + emphasis
        raw_text = _call_llm(system_prompt, user_prompt, temperature=0.7)
        code = raw_text.strip().strip("`")
        if code.lower().startswith("python"):
            code = code[len("python"):].strip()

        if _code_actually_fails(code, task):
            return SimulatedSubmission(
                task_id=task["id"], attempt_number=attempt_number, needs_clarification=False,
                submitted_code=code, clarification_text=None,
                intended_error_code=chosen_error["error_code"], raw_model_response=raw_text,
            )
        print(f"[INFO] Generisani 'buggy' kod je ipak prošao testove (pokušaj {gen_attempt+1}/{max_gen_attempts}), probam ponovo...")

    # Fallback -- koristi unaprijed pripremljen primjer iz common_errors (garantovano tačan ground truth)
    print(f"[FALLBACK] Koristim example_wrong_code za grešku '{chosen_error['error_code']}' iz task definicije.")
    return SimulatedSubmission(
        task_id=task["id"], attempt_number=attempt_number, needs_clarification=False,
        submitted_code=chosen_error["example_wrong_code"], clarification_text=None,
        intended_error_code=chosen_error["error_code"], raw_model_response="[FALLBACK - example_wrong_code]",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run test simulatora studenata (bez agenta)")
    parser.add_argument("--profile", required=True, choices=["fast_accurate", "common_errors", "slow_unsure"])
    parser.add_argument("--task-title", required=True, help="Tačan naslov zadatka iz baze (kolona title)")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    conn = _get_db_connection()
    try:
        profile = fetch_profile(conn, args.profile)
        task = fetch_task_by_title(conn, args.task_title)
    finally:
        conn.close()

    submission = generate_submission(profile, task, args.attempt, args.seed)

    print(json.dumps(submission.__dict__, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()