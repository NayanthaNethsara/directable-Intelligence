#!/usr/bin/env bash
# Serve a GGUF model with llama.cpp's OpenAI-compatible server (Metal-accelerated).
# API-only: the built-in web UI is disabled; talk to it via the controller service.
#
# Usage:
#   scripts/llm-server.sh                          # default: local Qwen3 0.6B GGUF
#   scripts/llm-server.sh models/foo.gguf          # any other local GGUF file
#   scripts/llm-server.sh unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M   # any HF repo:quant spec
#
# Requires: brew install llama.cpp
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:-models/Qwen_Qwen3-0.6B-Q4_K_M.gguf}"
PORT="${LLM_PORT:-8080}"

ARGS=(
  --host 127.0.0.1
  --port "$PORT"
  --ctx-size 4096
  --n-gpu-layers 99
  --jinja                 # use the model's chat template; needed for json_schema output
  --no-ui                 # API only, no browser UI
)

if [[ -f "$MODEL" ]]; then
  ARGS+=(--model "$MODEL")
else
  ARGS+=(-hf "$MODEL")
fi

# Qwen3 models "think" by default, which wastes the tiny token budget; turn it off.
if [[ "$MODEL" == *[Qq]wen3* ]]; then
  ARGS+=(--reasoning-budget 0)
fi

exec llama-server "${ARGS[@]}"
