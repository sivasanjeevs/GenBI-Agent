"""
harness.py – Evaluation harness (Checkpoint 4).

For each benchmark question:
  1. Run it `runs` times (default 3)
  2. Record: generated SQL, result data, response time, model used
  3. Check consistency: do all runs give the same answer?
  4. Compare against expected answer (if provided)

Results are written to eval_output/results_<timestamp>.json
and a summary table is printed to console.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger
from tabulate import tabulate

from app.config import settings


# ─── Result Data Classes ──────────────────────────────────────────────────────

def _empty_run_result() -> dict[str, Any]:
    return {
        "sql": "",
        "rows": [],
        "row_count": 0,
        "elapsed_ms": 0.0,
        "error": None,
        "model": settings.llm_model,
    }


# ─── Single Question Evaluation ───────────────────────────────────────────────

def _eval_question(
    question_id: str,
    question: str,
    difficulty: str,
    expected: Any | None,
    runs: int,
) -> dict[str, Any]:
    from app.answering.dates import resolve_dates
    from app.answering.retrieve import retrieve_relevant_semantics
    from app.answering.planner import plan_and_generate_sql
    from app.answering.executor import execute_with_repair
    from app.eval.compare import compare_results

    run_results: list[dict[str, Any]] = []

    for run_idx in range(runs):
        run_start = time.perf_counter()
        run_result = _empty_run_result()
        try:
            date_ctx = resolve_dates(question)
            semantics = retrieve_relevant_semantics(question)
            plan = plan_and_generate_sql(question, semantics, date_ctx)
            result = execute_with_repair(plan)

            run_result["sql"] = result.get("final_sql", plan["sql"])
            run_result["rows"] = result.get("rows", [])
            run_result["row_count"] = result.get("row_count", 0)
            run_result["elapsed_ms"] = result.get("elapsed_ms", 0.0)

        except ValueError as exc:
            run_result["error"] = f"UNANSWERABLE: {exc}"
        except Exception as exc:
            run_result["error"] = str(exc)

        run_result["total_elapsed_ms"] = (time.perf_counter() - run_start) * 1000
        run_results.append(run_result)
        logger.info(
            f"  Q{question_id} run {run_idx+1}/{runs}: "
            f"rows={run_result['row_count']} "
            f"elapsed={run_result['elapsed_ms']:.0f}ms "
            f"{'ERROR: ' + run_result['error'][:50] if run_result['error'] else 'OK'}"
        )

    # Consistency check: do all runs return the same data?
    successful_runs = [r for r in run_results if not r["error"]]
    is_consistent = False
    if len(successful_runs) == runs:
        first = successful_runs[0]["rows"]
        is_consistent = all(
            compare_results(r["rows"], first) for r in successful_runs[1:]
        )

    # Correctness check against expected answer
    is_correct = None
    if expected is not None and successful_runs:
        is_correct = compare_results(successful_runs[0]["rows"], expected)

    avg_elapsed = (
        sum(r["elapsed_ms"] for r in run_results) / len(run_results)
        if run_results else 0.0
    )

    return {
        "question_id": question_id,
        "question": question,
        "difficulty": difficulty,
        "runs": run_results,
        "is_consistent": is_consistent,
        "is_correct": is_correct,
        "avg_elapsed_ms": round(avg_elapsed, 2),
        "success_rate": round(len(successful_runs) / runs, 2),
        "model": settings.llm_model,
    }


# ─── Public Interface ─────────────────────────────────────────────────────────

def run_harness(
    benchmark_file: str | None = None,
    runs: int | None = None,
) -> Path:
    """
    Run the full evaluation harness.

    Args:
        benchmark_file: Path to JSON file with benchmark questions.
        runs: Number of repetitions per question.

    Returns:
        Path to the results JSON file.
    """
    bfile = Path(benchmark_file or settings.benchmark_file)
    n_runs = runs or settings.eval_runs

    if not bfile.exists():
        raise FileNotFoundError(f"Benchmark file not found: {bfile}")

    questions = json.loads(bfile.read_text())
    logger.info(f"Eval harness: {len(questions)} questions × {n_runs} runs")

    settings.eval_output_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []

    for q in questions:
        qid = str(q.get("id", "?"))
        question_text = q.get("question", "")
        difficulty = q.get("difficulty", "unknown")
        expected = q.get("expected_data", None)

        logger.info(f"\n[Q{qid}] ({difficulty}) {question_text}")

        result = _eval_question(qid, question_text, difficulty, expected, n_runs)
        all_results.append(result)

    # Summary metrics
    total = len(all_results)
    n_correct = sum(1 for r in all_results if r["is_correct"] is True)
    n_consistent = sum(1 for r in all_results if r["is_consistent"])
    n_answerable = sum(1 for r in all_results if r["success_rate"] > 0)
    avg_time = sum(r["avg_elapsed_ms"] for r in all_results) / total if total else 0

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": settings.llm_model,
        "total_questions": total,
        "answerable": n_answerable,
        "correct": n_correct,
        "consistent": n_consistent,
        "avg_elapsed_ms": round(avg_time, 2),
        "accuracy": round(n_correct / total, 3) if total else 0,
        "consistency_rate": round(n_consistent / total, 3) if total else 0,
        "results": all_results,
    }

    # Write results
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = settings.eval_output_dir / f"results_{ts}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    logger.success(f"Eval results written to {out_path}")

    # Print summary table
    table_rows = [
        [
            r["question_id"],
            r["difficulty"],
            r["question"][:50],
            "✓" if r["is_correct"] else ("?" if r["is_correct"] is None else "✗"),
            "✓" if r["is_consistent"] else "✗",
            f"{r['avg_elapsed_ms']:.0f}ms",
            f"{r['success_rate']*100:.0f}%",
        ]
        for r in all_results
    ]
    print("\n" + tabulate(
        table_rows,
        headers=["ID", "Level", "Question", "Correct", "Consistent", "Avg Time", "Success"],
        tablefmt="github",
    ))
    print(f"\nSummary: {n_correct}/{total} correct | {n_consistent}/{total} consistent | avg {avg_time:.0f}ms")

    return out_path


if __name__ == "__main__":
    run_harness()
