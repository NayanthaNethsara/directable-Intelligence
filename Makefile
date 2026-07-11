.PHONY: setup api llm llm-qwen test-fixture health

# One-time (and after dependency changes): create .venv and install deps.
setup:
	uv sync

# Run the controller API on :8000 with auto-reload.
api:
	uv run uvicorn controller_service.main:app --host 127.0.0.1 --port 8000 --reload

# Serve the local Qwen3 0.6B GGUF on :8080 (API only, no web UI).
llm:
	./scripts/llm-server.sh

health:
	curl -s http://localhost:8000/health | python3 -m json.tool

# Send one fixture through the model brain (FIXTURE=... BRAIN=... to override).
FIXTURE ?= fixtures/01_watch_our_right.json
BRAIN ?= model
test-fixture:
	curl -s -X POST "http://localhost:8000/decide?brain=$(BRAIN)" \
		-H "Content-Type: application/json" \
		-d @$(FIXTURE) | python3 -m json.tool
