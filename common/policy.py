"""
Zajednička pedagoška pravila -- IDENTIČNA u sve 4 framework implementacije.

Namjerno su deterministička (bez LLM poziva) da bi:
1. Poređenje frameworka bilo fer (ne testiramo "čija je pedagoška ideja
   bolja", nego "koliko efikasno/pouzdano svaki framework orkestrira
   ISTU logiku").
2. Rezultati bili reproducibilni (nema varijacije od poziva do poziva).

Ono što SVAKI framework radi na svoj način (i što se stvarno upoređuje)
je: dijagnoza tipa greške (LLM poziv) i generisanje teksta povratne
informacije (LLM poziv) -- te dvije stvari su namjerno OSTAVLJENE da ih
svaka implementacija odradi kroz svoj orkestracijski stil.
"""

from __future__ import annotations

MASTERY_INCREMENT_ON_CORRECT = 0.34
MAX_RETRIES_BEFORE_EASIER = 2


def update_mastery(current_mastery: float, is_correct: bool) -> float:
    if is_correct:
        return min(1.0, round(current_mastery + MASTERY_INCREMENT_ON_CORRECT, 3))
    return current_mastery


def decide_next_action(is_correct: bool, attempts_on_current_task: int) -> str:
    """Vraća 'advance' | 'retry' | 'easier' (vrijednosti odgovaraju NextAction enumu iz common/contract.py)."""
    if is_correct:
        return "advance"
    if attempts_on_current_task >= MAX_RETRIES_BEFORE_EASIER:
        return "easier"
    return "retry"