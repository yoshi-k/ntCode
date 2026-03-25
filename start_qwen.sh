#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start_qwen.sh
# Sets environment variables to point ntCode.py at a llama.cpp server
# running on nt-angband.local with the Qwen/Qwen3-27B model.
#
# llama.cpp exposes an OpenAI-compatible REST API, not an Anthropic one.
# The anthropic Python SDK respects ANTHROPIC_BASE_URL to redirect calls,
# but the wire format still differs.  The simplest zero-code-change approach
# is to use the OpenAI-compatible /v1 endpoint together with the
# OPENAI_* variables and swap the SDK — OR just point ANTHROPIC_BASE_URL at
# the llama.cpp server so the SDK sends requests there.
#
# If you later switch ntCode.py to the openai SDK you only need to change
# OPENAI_BASE_URL / OPENAI_API_KEY below.
# ---------------------------------------------------------------------------

# ----- llama.cpp server location ------------------------------------------
export LLAMA_CPP_HOST="nt-angband.local"
export LLAMA_CPP_PORT="8080"
export LLAMA_CPP_BASE_URL="http://${LLAMA_CPP_HOST}:${LLAMA_CPP_PORT}"

# ----- Model name (must match what llama.cpp reports) ----------------------
export ANTHROPIC_MODEL="Qwen/Qwen3-27B"

# ----- Redirect the Anthropic SDK to the llama.cpp OpenAI-compat endpoint -
# The anthropic SDK sends requests to  <ANTHROPIC_BASE_URL>/v1/messages
# llama.cpp listens on                 <base>/v1/chat/completions
# These are different paths, so a thin proxy or a local shim is the cleanest
# solution.  For a quick start we point the variable anyway; adjust if you
# add a proxy layer in front of llama.cpp.
export ANTHROPIC_BASE_URL="${LLAMA_CPP_BASE_URL}"

# A dummy key is required so the SDK does not refuse to initialise.
export ANTHROPIC_API_KEY="llama-cpp-no-key"

# ----- OpenAI-compat variables (handy if you switch the SDK) ---------------
export OPENAI_BASE_URL="${LLAMA_CPP_BASE_URL}/v1"
export OPENAI_API_KEY="llama-cpp-no-key"

# ---------------------------------------------------------------------------
echo "=========================================================="
echo " ntCode — llama.cpp backend"
echo "=========================================================="
echo "  Server : ${LLAMA_CPP_BASE_URL}"
echo "  Model  : ${ANTHROPIC_MODEL}"
echo "=========================================================="
echo ""

exec python3 ntCode.py "$@"
