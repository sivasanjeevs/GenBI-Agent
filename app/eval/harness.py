"""
harness.py – The Benchmark Runner (Phase 4 / Step 2).

Loads benchmark questions, runs the answering pipeline multiple times,
and calculates Accuracy, Consistency, Speed, and Resilience.

Outputs:
  - eval_output/results.json (Detailed per-run logs)
  - eval_output/summary.md   (Markdown summary report)
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from loguru import logger
from tabulate import tabulate

from app.answering.dates import resolve_dates
from app.answering.executor import execute_with_repair
from app.answering.planner import plan_and_generate_sql
from app.answering.retrieve import retrieve_relevant_semantics
from app.config import settings
from app.eval.compare import compare_results


def _empty_run_result() -> dict[str, Any]:
    return {
        "sql": "",
        "rows": [],
        "row_count": 0,
        "elapsed_ms": 0.0,
        "total_latency_ms": 0.0,
        "attempts": 0,
        "repaired": False,
        "abstained": False,
        "error": None,
        "model": settings.llm_model,
    }


def _run_single_pipeline(question: str) -> dict[str, Any]:
    """Execute the answering pipeline once."""
    start_time = time.perf_counter()
    run_result = _empty_run_result()

    try:
        date_ctx = resolve_dates(question)
        retrieval = retrieve_relevant_semantics(question)
        state = plan_and_generate_sql(question, retrieval, date_ctx)
        state = execute_with_repair(state)

        run_result["sql"] = state.sql
        run_result["rows"] = state.result.get("rows", [])
        run_result["row_count"] = state.result.get("row_count", 0)
        run_result["elapsed_ms"] = state.result.get("elapsed_ms", 0.0)
        run_result["attempts"] = state.attempts
        run_result["repaired"] = state.repaired
        run_result["abstained"] = state.abstained
        if state.abstained:
            run_result["error"] = state.abstain_reason

    except ValueError as exc:
        run_result["error"] = f"UNANSWERABLE: {exc}"
        run_result["abstained"] = True
    except Exception as exc:
        run_result["error"] = str(exc)
        run_result["abstained"] = True

    run_result["total_latency_ms"] = (time.perf_counter() - start_time) * 1000
    return run_result


def _eval_question(
    question_id: str,
    question: str,
    difficulty: str,
    expected_data: Any | None,
    runs: int,
) -> dict[str, Any]:
    """Run a single question multiple times and compute consistency/accuracy."""
    run_results: list[dict[str, Any]] = []

    for run_idx in range(runs):
        logger.info("Q{} run {}/{}...", question_id, run_idx + 1, runs)
        res = _run_single_pipeline(question)
        run_results.append(res)
        status = "ABSTAINED" if res["abstained"] else ("ERROR" if res["error"] else "OK")
        logger.debug(
            "  -> {} | rows: {} | latency: {:.0f}ms | attempts: {}",
            status, res["row_count"], res["total_latency_ms"], res["attempts"]
        )

    # Filter to runs that actually returned data (or 0-row successful queries)
    successful_runs = [r for r in run_results if not r["error"] and not r["abstained"]]

    # Consistency: do all runs (if any succeeded) return the exact same data?
    is_consistent = False
    if len(successful_runs) == runs:
        first_data = successful_runs[0]["rows"]
        is_consistent = all(compare_results(r["rows"], first_data) for r in successful_runs[1:])

    # Accuracy: does the first successful run match expected data?
    is_correct = None
    if expected_data is not None and successful_runs:
        # Evaluate accuracy based on the majority vote or just the first successful run.
        # We will use the first successful run here for simplicity.
        is_correct = compare_results(successful_runs[0]["rows"], expected_data)

    latencies = [r["total_latency_ms"] for r in run_results]
    retries = sum((r["attempts"] - 1) for r in run_results if r["attempts"] > 0)
    avg_retries = retries / runs if runs else 0.0

    return {
        "question_id": question_id,
        "question": question,
        "difficulty": difficulty,
        "runs": run_results,
        "is_consistent": is_consistent,
        "is_correct": is_correct,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "avg_retries": avg_retries,
        "success_rate": len(successful_runs) / runs,
    }


def _write_markdown_report(summary: dict[str, Any], path: Path) -> None:
    """Generate a markdown report of the evaluation metrics."""
    md = f"# Evaluation Harness Report\n\n"
    md += f"**Timestamp:** {summary['timestamp']}  \n"
    md += f"**Model:** {summary['model']}  \n"
    md += f"**Total Questions:** {summary['total_questions']}  \n\n"

    md += "## Key Metrics\n\n"
    md += f"- **Accuracy:** {summary['accuracy'] * 100:.1f}%\n"
    md += f"- **Consistency:** {summary['consistency_rate'] * 100:.1f}%\n"
    md += f"- **Answerability:** {summary['answerability_rate'] * 100:.1f}%\n"
    md += f"- **Resilience (Avg Retries):** {summary['avg_retries']:.2f} per question\n"
    md += f"- **Speed (p50 Latency):** {summary['p50_latency_ms']:.0f} ms\n"
    md += f"- **Speed (p95 Latency):** {summary['p95_latency_ms']:.0f} ms\n\n"

    md += "## Question Breakdown\n\n"
    
    headers = ["ID", "Level", "Question", "Correct", "Consistent", "Avg Time", "Avg Retries"]
    rows = []
    for r in summary["results"]:
        q_trunc = r["question"][:50] + ("..." if len(r["question"]) > 50 else "")
        correct = "✓" if r["is_correct"] else ("?" if r["is_correct"] is None else "✗")
        consistent = "✓" if r["is_consistent"] else "✗"
        rows.append([
            r["question_id"],
            r["difficulty"],
            q_trunc,
            correct,
            consistent,
            f"{r['avg_latency_ms']:.0f}ms",
            f"{r['avg_retries']:.1f}"
        ])

    md += tabulate(rows, headers=headers, tablefmt="github")
    md += "\n"
    path.write_text(md, encoding="utf-8")


def run_harness(
    benchmark_file: str | None = None,
    runs: int | None = None,
) -> None:
    """Run the benchmark suite and compute metrics."""
    bfile = Path(benchmark_file or settings.benchmark_file)
    n_runs = runs or settings.eval_runs

    if not bfile.exists():
        logger.error("Benchmark file not found: {}", bfile)
        # Create a dummy one for testing if it doesn't exist
        bfile.parent.mkdir(parents=True, exist_ok=True)
        bfile.write_text("[]", encoding="utf-8")
        logger.info("Created empty benchmark file at {}", bfile)

    questions = json.loads(bfile.read_text(encoding="utf-8"))
    logger.info("Starting eval harness: {} questions × {} runs", len(questions), n_runs)

    settings.eval_output_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []

    for q in questions:
        qid = str(q.get("id", "?"))
        q_text = q.get("question", "")
        diff = q.get("difficulty", "unknown")
        expected = q.get("expected_data")

        logger.info("\n=== Evaluating Q{} ===", qid)
        res = _eval_question(qid, q_text, diff, expected, n_runs)
        all_results.append(res)

    if not all_results:
        logger.warning("No questions evaluated.")
        return

    # ── Compute Suite Metrics ────────────────────────────────────────────────
    total = len(all_results)
    n_correct = sum(1 for r in all_results if r["is_correct"] is True)
    n_consistent = sum(1 for r in all_results if r["is_consistent"] is True)
    n_answerable = sum(1 for r in all_results if r["success_rate"] > 0)
    
    all_latencies = [
        run["total_latency_ms"] 
        for r in all_results for run in r["runs"]
    ]
    all_latencies.sort()
    
    p50_lat = all_latencies[len(all_latencies)//2] if all_latencies else 0.0
    p95_lat = all_latencies[int(len(all_latencies)*0.95)] if all_latencies else 0.0
    
    avg_retries = sum(r["avg_retries"] for r in all_results) / total if total else 0.0

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": settings.llm_model,
        "total_questions": total,
        "answerable": n_answerable,
        "correct": n_correct,
        "consistent": n_consistent,
        "accuracy": n_correct / total if total else 0.0,
        "consistency_rate": n_consistent / total if total else 0.0,
        "answerability_rate": n_answerable / total if total else 0.0,
        "avg_retries": avg_retries,
        "p50_latency_ms": p50_lat,
        "p95_latency_ms": p95_lat,
        "results": all_results,
    }

    # ── Write Outputs ────────────────────────────────────────────────────────
    ts = time.strftime("%Y%m%d_%H%M%S")
    
    # Detailed JSON
    json_path = settings.eval_output_dir / "results.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    
    # Snapshot JSON (for history)
    snap_path = settings.eval_output_dir / f"results_{ts}.json"
    snap_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # Markdown Summary
    md_path = settings.eval_output_dir / "summary.md"
    _write_markdown_report(summary, md_path)

    logger.success("Evaluation complete.")
    logger.success("JSON logs: {}", json_path)
    logger.success("Markdown summary: {}", md_path)

    print(f"\n--- EVALUATION SUMMARY ---")
    print(f"Accuracy:    {summary['accuracy']*100:.1f}% ({n_correct}/{total})")
    print(f"Consistency: {summary['consistency_rate']*100:.1f}% ({n_consistent}/{total})")
    print(f"Resilience:  {avg_retries:.2f} retries/question")
    print(f"Speed:       p50={p50_lat:.0f}ms, p95={p95_lat:.0f}ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GenBI Evaluation Harness")
    parser.add_argument("--runs", type=int, default=3, help="Number of repetitions per question")
    parser.add_argument("--benchmark", type=str, help="Path to benchmark JSON file")
    args = parser.parse_args()

    run_harness(benchmark_file=args.benchmark, runs=args.runs)
