# Rosetta – GenBI Agent

## Project Structure
```
rosetta/
├── app/
│   ├── main.py              # FastAPI app + routes
│   ├── config.py            # env loading
│   ├── db.py                # Oracle connection + safe execution
│   ├── llm.py               # LLM wrapper + disk cache
│   ├── learning/
│   │   ├── introspect.py    # schema, constraints
│   │   ├── profile.py       # value profiling
│   │   ├── patterns.py      # grain, joins, SCD, events, flags
│   │   ├── enrich.py        # LLM meanings
│   │   ├── verify.py        # run concepts as SQL to prove them
│   │   └── store.py         # semantic layer save/load/overrides
│   ├── answering/
│   │   ├── dates.py         # deterministic date resolver
│   │   ├── retrieve.py      # pick relevant semantics
│   │   ├── planner.py       # question -> plan -> SQL
│   │   ├── guard.py         # SELECT-only, sqlglot checks
│   │   ├── executor.py      # run + repair loop + vote
│   │   └── composer.py      # answer + explanation
│   └── eval/
│       ├── harness.py
│       └── compare.py
├── semantic_layer/          # generated JSON + overrides.yaml + changelog
├── eval_output/             # harness results (commit these)
├── benchmark/questions.json
├── frontend/                # optional UI
├── .env  (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Quickstart

### 1. Clone & install
```bash
git clone <your-repo>
cd rosetta
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env: fill in ORACLE_PASSWORD and your LLM API key
```

### 3. Run the learning pipeline
```bash
python -m app.learning.introspect   # introspect schema
python -m app.learning.profile      # profile values
python -m app.learning.patterns     # detect grain / joins / SCDs
python -m app.learning.enrich       # LLM meanings
python -m app.learning.verify       # validate as SQL
# semantic_layer/ is now populated
```

Or trigger via API:
```bash
uvicorn app.main:app --reload
curl -X POST http://localhost:8000/learn
```

### 4. Ask questions
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "List the active shops in Istanbul"}'
```

### 5. Run evaluation harness
```bash
python -m app.eval.harness
# Results written to eval_output/
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/learn` | Run full learning pipeline |
| GET | `/semantic-layer` | View current semantic layer |
| POST | `/semantic-layer/override` | Apply manual overrides |
| POST | `/ask` | Answer a business question |
| GET | `/ask/{question_id}/history` | Conversation follow-ups |
| POST | `/eval/run` | Trigger evaluation harness |
| GET | `/eval/results` | Latest harness results |
| GET | `/health` | Health check |

## Checkpoints

| # | Checkpoint | Status |
|---|-----------|--------|
| 1 | Learn the Data → Semantic Layer | 🔲 |
| 2 | Find the Right Data → SQL | 🔲 |
| 3 | Answer with Evidence | 🔲 |
| 4 | Prove It Works (Eval Harness) | 🔲 |
| 5 (Bonus) | Clarify & Converse | 🔲 |
| 6 (Bonus) | Visualise the Answer | 🔲 |

## Environment Variables

See `.env.example` for the full list. Critical vars:

| Variable | Description |
|----------|-------------|
| `ORACLE_HOST` | DB host (20.102.78.61) |
| `ORACLE_PORT` | DB port (1521) |
| `ORACLE_SERVICE` | Service name (FREEPDB1) |
| `ORACLE_USER` | Read-only user (VF_AGENT) |
| `ORACLE_PASSWORD` | **Never commit!** |
| `LLM_PROVIDER` | gemini / openai / anthropic / ollama |
| `LLM_MODEL` | e.g. gemini-2.0-flash |
| `GEMINI_API_KEY` | API key for Gemini |

## Model Used
- Primary: `gemini-2.0-flash` (Gemini free tier)

## Evaluation Output
See `eval_output/` for per-run results including generated SQL, answers, response times, and consistency scores.
