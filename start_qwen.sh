#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start_qwen.sh
# Launches ntCode.py backed by a llama.cpp server on nt-angband.local
# (currently serving Gemma 4; the name dates from an earlier Qwen setup).
#
# How it works
# ------------
# utils/config.py reads LLM_PROVIDER from the environment.  When it equals
# "openai", utils/llm._build_llm() builds providers.openai_chat.
# OpenAIChatProvider, which talks to any OpenAI-compatible server, including
# llama.cpp (POST /v1/chat/completions) with native tool calling.  Start
# llama-server with --jinja so it parses the model's tool calls; otherwise
# set CALLING_CONVENTION to a text dialect (e.g. gemma).
#
# Variables consumed by utils/config.py
# -------------------------------------
#   LLM_PROVIDER       "openai"  → OpenAI-compatible endpoint instead of Claude
#   OPENAI_BASE_URL    root URL of the llama.cpp /v1 endpoint
#   OPENAI_API_KEY     any non-empty string (llama.cpp ignores it)
#   OPENAI_MODEL       model name the server was started with
#   OPENAI_MAX_TOKENS  0 = let the server decide (omitted from request)
#   OPENAI_TEMPERATURE sampling temperature
#   OPENAI_TIMEOUT     per-request timeout in seconds
#   OPENAI_MAX_RETRIES attempts per request on transient errors
#   CALLING_CONVENTION unset = native tools; ntcode/xml/json_block/gemma = text
#
# ANTHROPIC_API_KEY is not needed for this setup; the dummy value below is
# harmless.
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
#export OPENAI_MODEL='unsloth/Qwen3.6-27B-GGUF:UD-Q6_K_XL'
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
