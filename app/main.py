"""
main.py – FastAPI application entry point.

Endpoints:
  POST  /learn                  – run full learning pipeline
  GET   /semantic-layer         – view current semantic layer
  POST  /semantic-layer/override – apply manual overrides
  POST  /ask                    – answer a business question
  GET   /ask/{question_id}/history – fetch conversation history (bonus CP5)
  POST  /eval/run               – run evaluation harness
  GET   /eval/results           – latest harness results
  GET   /health                 – liveness check
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.db import close_pool, init_pool


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Rosetta starting up…")
    init_pool()
    yield
    close_pool()
    logger.info("Rosetta shut down")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Rosetta – GenBI Agent",
    description=(
        "A GenBI agent that learns an Oracle database from its schema and values, "
        "captures that knowledge in a semantic layer, and answers business questions."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response Models ────────────────────────────────────────────────

class LearnRequest(BaseModel):
    schemas: list[str] | None = None          # defaults to config
    force_refresh: bool = False               # bypass LLM cache

class LearnResponse(BaseModel):
    status: str
    message: str
    semantic_layer_path: str

class AskRequest(BaseModel):
    question: str
    conversation_id: str | None = None        # for follow-up (CP5)
    date_context: str | None = None           # e.g. "today is 2026-08-28"

class AskResponse(BaseModel):
    question_id: str
    answer: str
    sql: str
    data: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    elapsed_ms: float
    date_interpretation: str | None = None
    explanation: str
    chart: dict[str, Any] | None = None       # CP6 bonus

class OverrideRequest(BaseModel):
    overrides: dict[str, Any]                 # merged into overrides.yaml

class EvalRunRequest(BaseModel):
    benchmark_file: str | None = None
    runs: int | None = None                   # defaults to config EVAL_RUNS


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post("/learn", response_model=LearnResponse, tags=["Learning"])
async def learn(req: LearnRequest, background_tasks: BackgroundTasks):
    """
    Trigger the full learning pipeline:
    1. Introspect schema + constraints
    2. Profile column values
    3. Detect grain, joins, SCDs, events, flags
    4. Enrich with LLM meanings
    5. Verify concepts as SQL
    6. Save semantic layer to disk
    """
    from app.learning.introspect import introspect_schemas
    from app.learning.profile import profile_schemas
    from app.learning.patterns import detect_patterns
    from app.learning.enrich import enrich_with_llm
    from app.learning.verify import verify_concepts
    from app.learning.store import save_semantic_layer

    schemas = req.schemas or settings.schemas
    logger.info(f"Learning pipeline started | schemas={schemas}")

    try:
        schema_info = introspect_schemas(schemas)
        profiled = profile_schemas(schema_info)
        patterns = detect_patterns(profiled)
        enriched = enrich_with_llm(patterns, bypass_cache=req.force_refresh)
        verified = verify_concepts(enriched)
        path = save_semantic_layer(verified)
        return LearnResponse(
            status="success",
            message=f"Semantic layer built for {len(schemas)} schema(s), saved to {path}",
            semantic_layer_path=str(path),
        )
    except Exception as exc:
        logger.exception("Learning pipeline failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/semantic-layer", tags=["Learning"])
def get_semantic_layer() -> dict[str, Any]:
    """Return the current semantic layer JSON."""
    from app.learning.store import load_semantic_layer

    layer = load_semantic_layer()
    if layer is None:
        raise HTTPException(status_code=404, detail="Semantic layer not found. Run /learn first.")
    return layer


@app.post("/semantic-layer/override", tags=["Learning"])
def apply_overrides(req: OverrideRequest) -> dict[str, str]:
    """Apply manual corrections to the semantic layer (recorded in changelog)."""
    from app.learning.store import apply_overrides

    apply_overrides(req.overrides)
    return {"status": "ok", "message": "Overrides applied and semantic layer updated"}


@app.post("/ask", response_model=AskResponse, tags=["Answering"])
def ask(req: AskRequest) -> AskResponse:
    """
    Answer a natural-language business question.
    Runs: date resolution → retrieval → planning → SQL generation →
          guard → execution (with repair loop) → answer composition.
    """
    from app.answering.dates import resolve_dates
    from app.answering.retrieve import retrieve_relevant_semantics
    from app.answering.planner import plan_and_generate_sql
    from app.answering.executor import execute_with_repair
    from app.answering.composer import compose_answer

    question_id = str(uuid.uuid4())
    logger.info(f"Question [{question_id}]: {req.question!r}")

    try:
        date_ctx = resolve_dates(req.question, date_context=req.date_context)
        semantics = retrieve_relevant_semantics(req.question)
        plan = plan_and_generate_sql(
            question=req.question,
            semantics=semantics,
            date_context=date_ctx,
            conversation_id=req.conversation_id,
        )
        result = execute_with_repair(plan)
        response = compose_answer(
            question=req.question,
            plan=plan,
            result=result,
            date_context=date_ctx,
            question_id=question_id,
        )
        return AskResponse(**response)

    except ValueError as exc:
        # Unanswerable questions – return a graceful "I don't know"
        logger.warning(f"Unanswerable: {exc}")
        return AskResponse(
            question_id=question_id,
            answer=str(exc),
            sql="",
            data=[],
            columns=[],
            row_count=0,
            elapsed_ms=0.0,
            explanation="The data cannot answer this question.",
        )
    except Exception as exc:
        logger.exception("Ask pipeline failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/ask/{conversation_id}/history", tags=["Answering"])
def get_history(conversation_id: str) -> list[dict[str, Any]]:
    """Return conversation history for follow-up questions (Bonus CP5)."""
    from app.answering.composer import get_conversation_history

    history = get_conversation_history(conversation_id)
    if not history:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return history


@app.post("/eval/run", tags=["Evaluation"])
async def run_eval(req: EvalRunRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Trigger the evaluation harness (runs in background)."""
    from app.eval.harness import run_harness

    background_tasks.add_task(
        run_harness,
        benchmark_file=req.benchmark_file,
        runs=req.runs,
    )
    return {"status": "started", "message": "Evaluation harness running in background"}


@app.get("/eval/results", tags=["Evaluation"])
def eval_results() -> dict[str, Any]:
    """Return the latest evaluation harness results."""
    import json
    from pathlib import Path

    results_dir = settings.eval_output_dir
    files = sorted(results_dir.glob("results_*.json"), reverse=True)
    if not files:
        raise HTTPException(status_code=404, detail="No eval results found. Run /eval/run first.")
    latest = json.loads(files[0].read_text())
    return latest


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=True,
    )
