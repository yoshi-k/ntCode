#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start_qwen.sh
# Launches ntCode.py backed by a llama.cpp server on nt-angband.local
# running the Qwen/Qwen3-27B model.
#
# How it works
# ------------
# utils/config.py reads LLM_PROVIDER from the environment.  When it equals
# "openai", utils/llm._build_llm() instantiates utils/openai_llm.OpenAILLM
# which talks to any OpenAI-compatible HTTP server — including llama.cpp
# running in --server mode (POST /v1/chat/completions).
#
# No proxy is required; llama.cpp speaks the OpenAI wire protocol natively.
#
# Variables consumed by utils/config.py
# -------------------------------------
#   LLM_PROVIDER       "openai"  → use OpenAILLM instead of AnthropicLLM
#   OPENAI_BASE_URL    root URL of the llama.cpp /v1 endpoint
#   OPENAI_API_KEY     any non-empty string (llama.cpp ignores it)
#   OPENAI_MODEL       model name the server was started with
#   OPENAI_MAX_TOKENS  0 = let the server decide (omitted from request)
#   OPENAI_TEMPERATURE sampling temperature
#   OPENAI_TIMEOUT     per-request timeout in seconds
#   OPENAI_MAX_RETRIES SDK-level retry attempts on transient errors
#
# ANTHROPIC_API_KEY is still set to a dummy value so that the Anthropic SDK
# import inside utils/llm.py does not raise an error at module load time
# (the import happens before the provider branch is evaluated).
# ---------------------------------------------------------------------------

# ----- llama.cpp server location -------------------------------------------
LLAMA_HOST="nt-angband.local"
LLAMA_PORT="8080"

# ----- LLM provider: use the OpenAI-compatible path ------------------------
export LLM_PROVIDER="openai"

# ----- OpenAI-compatible settings (read by utils/config.py) ----------------
#export OPENAI_BASE_URL="http://${LLAMA_HOST}:${LLAMA_PORT}/v1"
export OPENAI_BASE_URL="http://192.168.2.126:8080/v1"
export OPENAI_API_KEY="llama-cpp-no-key"   # any non-empty string
#export OPENAI_MODEL="Qwen/Qwen3-27B"       # must match the loaded GGUF
export OPENAI_MODEL="gemma-4-26B-A4B-it-UD-Q8_K_XL.gguf"
export OPENAI_MAX_TOKENS="0"               # 0 = omit, let server decide
export OPENAI_TEMPERATURE="0.7"
export OPENAI_TIMEOUT="120.0"              # seconds; raise for slow GPUs
export OPENAI_MAX_RETRIES="3"

# ----- Dummy Anthropic key (suppresses SDK import-time warnings) -----------
export ANTHROPIC_API_KEY="llama-cpp-no-key"

# ----- Rate limiter: relax for a local server (utils/config.py) ------------
export NTCODE_TOKEN_LIMIT_PER_MINUTE="500000"

# ---------------------------------------------------------------------------
echo "=========================================================="
echo " ntCode — llama.cpp  (OpenAI-compatible backend)"
echo "=========================================================="
echo "  Server : ${OPENAI_BASE_URL}"
echo "  Model  : ${OPENAI_MODEL}"
echo "=========================================================="
echo ""

exec python3 ntCode.py "$@"
