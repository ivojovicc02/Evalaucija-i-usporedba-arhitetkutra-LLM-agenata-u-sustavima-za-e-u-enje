"""
Sandbox servis za izvršavanje studentskog Python koda protiv test-case-ova.

Namjerno je ODVOJEN od agentne logike -- svaki od 4 frameworka (LangGraph,
CrewAI, LlamaIndex Workflows, OpenAI Agents SDK) poziva OVAJ isti servis
preko HTTP-a. Ovo osigurava da je provjera tačnosti identična i nezavisna
od toga koji agent framework se testira (fer poređenje).

Pokretanje samostalno (bez docker-compose) radi brzog testiranja:
    uvicorn executor:app --port 8090
"""

import io
import contextlib
import multiprocessing
import traceback
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ELT Agents Sandbox Executor")


class TestCase(BaseModel):
    input: Any = None          # proslijeđeno kao stdin ili poziv funkcije, ovisno o task tipu
    expected_output: str


class ExecuteRequest(BaseModel):
    code: str
    test_cases: list[TestCase]
    timeout_seconds: float = 3.0
    entry_point: str | None = None  # ime funkcije koju treba pozvati, ako task tip nije stdin-based


class TestResult(BaseModel):
    passed: bool
    actual_output: str | None = None
    error: str | None = None


class ExecuteResponse(BaseModel):
    results: list[TestResult]
    pass_count: int
    total_count: int
    all_passed: bool


def _run_stdin_case(code: str, stdin_data: str, result_queue: multiprocessing.Queue) -> None:
    """Izvršava kod u zasebnom procesu, hvata stdout, forsira stdin."""
    import sys

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(str(stdin_data) if stdin_data is not None else "")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, {"__name__": "__main__"})
        result_queue.put({"ok": True, "output": buf.getvalue()})
    except Exception:
        result_queue.put({"ok": False, "error": traceback.format_exc(limit=3)})
    finally:
        sys.stdin = old_stdin


def _run_function_case(code: str, entry_point: str, arg: Any, result_queue: multiprocessing.Queue) -> None:
    """Izvršava kod, poziva imenovanu funkciju s argumentom, hvata povratnu vrijednost."""
    namespace: dict[str, Any] = {}
    try:
        exec(code, namespace)
        fn = namespace.get(entry_point)
        if fn is None:
            result_queue.put({"ok": False, "error": f"Funkcija '{entry_point}' nije definisana."})
            return
        if isinstance(arg, (list, tuple)):
            out = fn(*arg)
        elif isinstance(arg, dict):
            out = fn(**arg)
        elif arg is None:
            out = fn()
        else:
            out = fn(arg)
        result_queue.put({"ok": True, "output": str(out)})
    except Exception:
        result_queue.put({"ok": False, "error": traceback.format_exc(limit=3)})


def _execute_isolated(code: str, test_case: TestCase, entry_point: str | None, timeout: float) -> TestResult:
    q: multiprocessing.Queue = multiprocessing.Queue()
    target = _run_function_case if entry_point else _run_stdin_case
    args = (code, entry_point, test_case.input, q) if entry_point else (code, test_case.input, q)

    proc = multiprocessing.Process(target=target, args=args)
    proc.start()
    proc.join(timeout)

    if proc.is_alive():
        proc.terminate()
        proc.join()
        return TestResult(passed=False, error=f"Timeout > {timeout}s (moguća beskonačna petlja)")

    if q.empty():
        return TestResult(passed=False, error="Proces nije vratio rezultat (crash).")

    res = q.get()
    if not res["ok"]:
        return TestResult(passed=False, error=res["error"])

    actual = res["output"].strip()
    expected = test_case.expected_output.strip()
    return TestResult(passed=actual == expected, actual_output=actual)


@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
    results = [
        _execute_isolated(req.code, tc, req.entry_point, req.timeout_seconds)
        for tc in req.test_cases
    ]
    pass_count = sum(r.passed for r in results)
    return ExecuteResponse(
        results=results,
        pass_count=pass_count,
        total_count=len(results),
        all_passed=pass_count == len(results),
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}