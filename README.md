# 🚀 Rosetta – GenBI Agent

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![Oracle 23ai](https://img.shields.io/badge/Database-Oracle%2023ai-red.svg)
![Gemini AI](https://img.shields.io/badge/LLM-Google%20Gemini-orange.svg)
![Status](https://img.shields.io/badge/Status-Hackathon%20Ready-success.svg)

**Rosetta** is an advanced, autonomous Generative Business Intelligence (GenBI) agent built for the **DataGenie Engineering Hackathon 2026**. 

Unlike traditional Text-to-SQL tools that rely on manually hardcoded definitions, Rosetta operates autonomously. It dynamically introspects the database, profiles data values, detects complex schema patterns (SCD Type 2, fact/dimension, grain), and leverages LLMs to generate a robust semantic layer on the fly. 

## ✨ Key Features

* **🧠 Autonomous Semantic Learning**: Automatically learns schema relationships, table grains, and decodes cryptic status codes into a human-readable semantic layer.
* **🛡️ Self-Healing SQL Generation**: Implements an intelligent repair loop. If a generated query fails on execution, the agent receives the Oracle error context and dynamically rewrites the query.
* **📊 Context-Aware Answering**: Understands relative dates (e.g., "last month") and dynamically resolves them to deterministic values before planning queries.
* **⚡ Highly Optimized LLM Usage**: Employs aggressive disk caching and parallel execution to minimize token usage and API latency.
* **🧪 Integrated Eval Harness**: Includes a fully automated benchmarking suite to test against ground-truth questions and evaluate the consistency, speed, and accuracy of the semantic layer.
* **💬 Interactive UI**: Includes a modern, React-based web interface for seamless multi-turn conversations and rich chart visualisations.

---

## 🏗️ Architecture & Pipeline

[View the Architecture Diagram on Figma](https://www.figma.com/board/4cnYCwRrL5Ph5rcMpAQ8av/GenBI-agent?node-id=0-1&t=0Se0a7V6rOCf4ES0-1)

---

## 🏗️ Architecture explaination and demo video 

[demo video](https://drive.google.com/file/d/19IbHEoeDS-f5FMRz7fGruyp1jiXgSqpN/view?usp=sharing)

---

## ⚙️ Local Setup & Installation

### 1. Prerequisites
* Python 3.11+
* Oracle Database 23ai Client / Instant Client
* Gemini API Key

### 2. Clone & Install
```bash
git clone <your-repo-url>
cd rosetta
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy the `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```
Ensure the following variables are set in your `.env` file:
```ini
ORACLE_HOST=20.102.78.61
ORACLE_PORT=1521
ORACLE_SERVICE=FREEPDB1
ORACLE_USER=VF_AGENT
ORACLE_PASSWORD=your_oracle_password_here
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 🚀 Usage

### Starting the Server
Rosetta provides a robust FastAPI backend. Start the server using `uvicorn`:
```bash
python -m uvicorn app.main:app --reload
```

### Starting the UI
Rosetta also provides a React-based interactive web interface. To run it:
```bash
cd frontend
npm install
npm run dev
```

### Step 1: Train the Agent (Build Semantic Layer)
Before asking questions, point the agent at the database so it can learn the data relationships:
```bash
curl -X POST http://localhost:8000/learn
```
*Note: This will perform deep introspection. Progress bars will be visible in the server logs. The resulting semantic layer is saved to `semantic_layer/semantic_layer.json`.*

### Step 2: Ask Business Questions
Once the semantic layer is built, you can query the agent in natural language:
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "List the active shops in Istanbul"}'
```

### Step 3: Run the Evaluation Benchmark
Validate the agent's performance against the benchmark questions:
```bash
curl -X POST http://localhost:8000/eval/run
```
*Results are automatically saved to the `eval_output/` directory.*

---

## 📚 API Reference

| HTTP Method | Endpoint | Description |
|---|---|---|
| `POST` | `/learn` | Trigger the autonomous DB learning pipeline. |
| `GET` | `/semantic-layer` | View the generated semantic layer definition. |
| `POST` | `/semantic-layer/override` | Apply manual, auditable corrections to semantics. |
| `POST` | `/ask` | Submit a natural language question. |
| `GET` | `/ask/{conversation_id}/history` | Fetch context for conversational follow-ups. |
| `POST` | `/eval/run` | Execute the evaluation harness. |
| `GET` | `/eval/results` | Fetch the latest evaluation harness results. |
| `GET` | `/health` | Check API health status. |

---

## 🏆 Hackathon Checkpoints

- [x] **Checkpoint 1: Learn the Data** (Automated semantic layer generation)
- [x] **Checkpoint 2: Find the Right Data** (LLM query planning & generation)
- [x] **Checkpoint 3: Answer with Evidence** (SQL tracing & data explanation)
- [x] **Checkpoint 4: Prove It Works** (Automated eval harness)
- [x] **Checkpoint 5 (Bonus): Clarify & Converse** (Multi-turn conversations)
- [x] **Checkpoint 6 (Bonus): Visualise the Answer** (Chart generation)

---
*Built with ❤️ for the DataGenie Engineering Hackathon 2026.*
