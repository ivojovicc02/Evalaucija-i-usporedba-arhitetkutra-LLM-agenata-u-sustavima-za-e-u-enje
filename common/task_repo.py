"""
Zajednički pristup bazi za zadatke i koncepte -- koriste ga sve 4
framework implementacije. Ovo NIJE dio agentne logike (nema odlučivanja),
samo čist pristup podacima -- svrha je izbjeći da svaka implementacija
piše (i moguće pogrešno kopira) isti SQL četiri puta.
"""

from __future__ import annotations

import os
from typing import Optional

import psycopg2
import psycopg2.extras

DB_HOST = os.environ.get("ELT_DB_HOST", "localhost")
DB_PORT = os.environ.get("ELT_DB_PORT", "5432")
DB_NAME = os.environ.get("ELT_DB_NAME", "elt_agents")
DB_USER = os.environ.get("ELT_DB_USER", "elt_admin")
DB_PASSWORD = os.environ.get("ELT_DB_PASSWORD", "change_me_locally")


def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def fetch_task(conn, task_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.code AS concept_code, c.order_index AS concept_order_index
            FROM tasks t JOIN concepts c ON t.concept_id = c.id
            WHERE t.id = %s;
            """,
            (task_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Nepoznat task_id: {task_id}")
        return row


def fetch_task_by_title(conn, title: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.code AS concept_code, c.order_index AS concept_order_index
            FROM tasks t JOIN concepts c ON t.concept_id = c.id
            WHERE t.title = %s;
            """,
            (title,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Nepoznat zadatak: {title}")
        return row


def fetch_next_concept_first_task(conn, current_concept_order_index: int) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.code AS concept_code, c.order_index AS concept_order_index
            FROM tasks t JOIN concepts c ON t.concept_id = c.id
            WHERE c.order_index > %s AND t.difficulty = 1
            ORDER BY c.order_index LIMIT 1;
            """,
            (current_concept_order_index,),
        )
        return cur.fetchone()


def fetch_harder_task_same_concept(conn, task: dict) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.code AS concept_code, c.order_index AS concept_order_index
            FROM tasks t JOIN concepts c ON t.concept_id = c.id
            WHERE t.concept_id = %s AND t.difficulty > %s
            ORDER BY t.difficulty LIMIT 1;
            """,
            (task["concept_id"], task["difficulty"]),
        )
        return cur.fetchone()


def fetch_easier_task_same_concept(conn, task: dict) -> Optional[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.*, c.code AS concept_code, c.order_index AS concept_order_index
            FROM tasks t JOIN concepts c ON t.concept_id = c.id
            WHERE t.concept_id = %s AND t.difficulty < %s
            ORDER BY t.difficulty DESC LIMIT 1;
            """,
            (task["concept_id"], task["difficulty"]),
        )
        return cur.fetchone()


def resolve_advance_task(conn, current_task: dict) -> Optional[dict]:
    """Sljedeći zadatak pri ADVANCE akciji: teži u istom konceptu, ili prvi
    iz sljedećeg koncepta, ili None ako je sve gradivo savladano (COMPLETE)."""
    harder = fetch_harder_task_same_concept(conn, current_task)
    if harder:
        return harder
    return fetch_next_concept_first_task(conn, current_task["concept_order_index"])


def resolve_easier_task(conn, current_task: dict) -> Optional[dict]:
    """Sljedeći zadatak pri EASIER akciji: lakši u istom konceptu, ili
    fallback na isto pravilo kao ADVANCE ako nema lakšeg (rijedak slučaj)."""
    easier = fetch_easier_task_same_concept(conn, current_task)
    if easier:
        return easier
    return resolve_advance_task(conn, current_task)