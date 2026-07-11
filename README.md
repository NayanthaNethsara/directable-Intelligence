# Directable Intelligence

An open framework for real-time, on-device co-op game companions.

This repo contains the **controller service**: a small FastAPI server that a
Unity game calls once per controller tick. The game sends a serialized spatial
scene graph (SSG), a context digest, and any pending player command; the
service returns one structured decision (`skill`, `target`, `ack`,
`command_status`, `proposal`).

Two interchangeable "brains" produce decisions:

- **heuristic** — deterministic rule ladder, no dependencies, ~0 ms. Baseline
  and fallback.
- **model** — a local LLM served over an OpenAI-compatible API (llama.cpp,
  Ollama, LM Studio, vLLM — anything that speaks the protocol). Output is
  constrained to the decision schema via `json_schema` structured output.

Every decision is validated and, if necessary, repaired to a safe `Hold` —
a bad model output can never crash the game loop. All decisions are logged to
JSONL for offline analysis.

## Requirements

- macOS (Apple Silicon recommended) or Linux
- [uv](https://docs.astral.sh/uv/) — Python environment manager
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — local model server

```bash
brew install uv llama.cpp
```

## Setup

```bash
make setup          # creates .venv (Python 3.12) and installs dependencies
cp .env.example .env   # optional: only needed to override defaults
```

## Run

Two processes, two terminals:

```bash
# Terminal 1 — the LLM (local Qwen3 0.6B GGUF in models/; API only, no web UI)
make llm

# Terminal 2 — the controller API on :8000
make api
```

Smoke test:

```bash
make health
make test-fixture                                    # model brain, fixture 01
make test-fixture BRAIN=heuristic                    # rule-based brain, no LLM needed
make test-fixture FIXTURE=fixtures/03_infeasible_command.json
```

## Choosing a model

The service is model-agnostic: point `scripts/llm-server.sh` at any GGUF.

```bash
make llm                                             # local Qwen3 0.6B (default; fastest, ~0.7 s/decision)
./scripts/llm-server.sh bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M  # any HF repo:quant (auto-download)
./scripts/llm-server.sh models/your-model.gguf       # any local file
```

Measured on an M4 MacBook (16 GB): Qwen3 0.6B ≈ 0.7 s per decision,
Llama 3.2 3B ≈ 1.5–2 s (higher decision quality). Latency is logged per
decision (`latency_ms`).

To use **Ollama** instead of llama.cpp, set in `.env`:

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.2:3b
```

## Configuration

All settings live in [.env.example](.env.example) (copy to `.env`):
LLM endpoint, model label, temperature, max tokens, request timeout,
default brain, and log directory.

## API

- `POST /decide?brain=model|heuristic` — request/response schemas in
  [controller_service/schema.py](controller_service/schema.py); example
  payloads in [fixtures/](fixtures/) and a Postman collection in
  [fixtures/postman_collection.json](fixtures/postman_collection.json).
- `GET /health` — liveness plus available brains and current log file.

## Project layout

```
controller_service/
  main.py           # FastAPI app: /decide, /health, validate-or-repair, JSONL logging
  schema.py         # the external contract (request/response models)
  config.py         # pydantic-settings; reads .env
  brains/
    base.py         # Brain interface
    heuristic.py    # rule-based baseline
    model.py        # local LLM via OpenAI-compatible API + json_schema output
fixtures/           # sample /decide payloads
scripts/llm-server.sh   # launches llama.cpp with sane defaults
models/             # local GGUF weights (gitignored)
logs/               # decision JSONL logs (gitignored)
```
