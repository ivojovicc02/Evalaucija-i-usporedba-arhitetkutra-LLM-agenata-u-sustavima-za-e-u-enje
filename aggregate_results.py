"""
Agregira `interaction_logs` u tabelu metrika po frameworku -- glavni
izlaz za poglavlje 5 (Evaluacija i rezultati) diplomskog rada.

Proizvodi:
1. Ispis tabele u terminalu (za brz pregled)
2. CSV fajl (results/aggregate_summary.csv) -- lako uvesti u Word/Excel
   tabelu za sam rad

Pokretanje (iz korijena projekta):
    py aggregate_results.py
"""

from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from common import task_repo

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _fetch_frameworks(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT framework_code FROM interaction_logs ORDER BY framework_code;")
        return [row["framework_code"] for row in cur.fetchall()]


def _aggregate_for_framework(conn, framework_code: str) -> dict:
    with conn.cursor() as cur:
        # Osnovni brojevi
        cur.execute(
            "SELECT COUNT(*) AS n FROM interaction_logs WHERE framework_code = %s;",
            (framework_code,),
        )
        total_rows = cur.fetchone()["n"]

        # Metrike performansi -- samo redovi gdje je stvarno bio submission (ne uvodni korak)
        cur.execute(
            """
            SELECT
                AVG(latency_ms)::numeric(10,1) AS avg_latency_ms,
                AVG(llm_call_count)::numeric(10,2) AS avg_llm_calls,
                AVG(input_tokens)::numeric(10,1) AS avg_input_tokens,
                AVG(output_tokens)::numeric(10,1) AS avg_output_tokens,
                COUNT(*) AS n_submissions
            FROM interaction_logs
            WHERE framework_code = %s AND test_total_count IS NOT NULL;
            """,
            (framework_code,),
        )
        perf = cur.fetchone()

        # Tačnost rješenja (koliko je podnesaka bilo tačno)
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_correct = true) AS n_correct,
                COUNT(*) FILTER (WHERE is_correct = false) AS n_incorrect
            FROM interaction_logs
            WHERE framework_code = %s AND is_correct IS NOT NULL;
            """,
            (framework_code,),
        )
        correctness = cur.fetchone()

        # Tačnost dijagnoze greške -- samo za redove gdje JE bilo netačno (pa je dijagnoza pokušana)
        cur.execute(
            """
            SELECT
                COUNT(*) AS n_diagnosis_attempts,
                COUNT(*) FILTER (WHERE detected_error_code = actual_error_code) AS n_diagnosis_correct
            FROM interaction_logs
            WHERE framework_code = %s AND is_correct = false AND actual_error_code IS NOT NULL;
            """,
            (framework_code,),
        )
        diagnosis = cur.fetchone()

        # Robusnost -- greške u izvršavanju
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE error_occurred = true) AS n_errors FROM interaction_logs WHERE framework_code = %s;",
            (framework_code,),
        )
        robustness = cur.fetchone()

    n_correct = correctness["n_correct"] or 0
    n_incorrect = correctness["n_incorrect"] or 0
    n_total_graded = n_correct + n_incorrect
    correctness_rate = round(n_correct / n_total_graded, 3) if n_total_graded else None

    n_diag_attempts = diagnosis["n_diagnosis_attempts"] or 0
    n_diag_correct = diagnosis["n_diagnosis_correct"] or 0
    diagnosis_accuracy = round(n_diag_correct / n_diag_attempts, 3) if n_diag_attempts else None

    return {
        "framework": framework_code,
        "total_interakcija": total_rows,
        "prosjecna_latencija_ms": float(perf["avg_latency_ms"]) if perf["avg_latency_ms"] is not None else None,
        "prosjecan_broj_llm_poziva": float(perf["avg_llm_calls"]) if perf["avg_llm_calls"] is not None else None,
        "prosjecni_input_tokeni": float(perf["avg_input_tokens"]) if perf["avg_input_tokens"] is not None else None,
        "prosjecni_output_tokeni": float(perf["avg_output_tokens"]) if perf["avg_output_tokens"] is not None else None,
        "n_podnesaka": perf["n_submissions"],
        "tacnost_rjesenja": correctness_rate,
        "n_tacno": n_correct,
        "n_netacno": n_incorrect,
        "tacnost_dijagnoze_greske": diagnosis_accuracy,
        "n_dijagnoza_pokusaja": n_diag_attempts,
        "broj_grešaka_izvrsavanja": robustness["n_errors"],
    }


def main() -> None:
    conn = task_repo.get_connection()
    try:
        frameworks = _fetch_frameworks(conn)
        if not frameworks:
            print("Nema podataka u interaction_logs -- pokreni prvo run_full_simulation.py.")
            return

        results = [_aggregate_for_framework(conn, fw) for fw in frameworks]
    finally:
        conn.close()

    # --- Ispis u terminalu ---
    print("\n" + "=" * 100)
    print("SAŽETAK METRIKA PO FRAMEWORKU")
    print("=" * 100)
    for r in results:
        print(f"\n--- {r['framework']} ---")
        print(f"  Ukupno interakcija logovano:      {r['total_interakcija']}")
        print(f"  Prosječna latencija:              {r['prosjecna_latencija_ms']} ms")
        print(f"  Prosječan broj LLM poziva:         {r['prosjecan_broj_llm_poziva']}")
        print(f"  Prosječni input tokeni:            {r['prosjecni_input_tokeni']}")
        print(f"  Prosječni output tokeni:           {r['prosjecni_output_tokeni']}")
        print(f"  Tačnost rješenja (tačno/ukupno):   {r['tacnost_rjesenja']} ({r['n_tacno']}/{r['n_tacno'] + r['n_netacno']})")
        print(f"  Tačnost dijagnoze greške:          {r['tacnost_dijagnoze_greske']} (na {r['n_dijagnoza_pokusaja']} pokušaja)")
        print(f"  Broj grešaka u izvršavanju:        {r['broj_grešaka_izvrsavanja']}")

    # --- CSV export ---
    os.makedirs(RESULTS_DIR, exist_ok=True)
    csv_path = os.path.join(RESULTS_DIR, "aggregate_summary.csv")
    fieldnames = list(results[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n{'=' * 100}")
    print(f"CSV sažetak sačuvan u: {csv_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()