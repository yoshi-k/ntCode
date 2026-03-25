#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# start_qwen.sh
# Configures the environment for ntCode.py to use a llama.cpp server
# running on nt-angband.local with the Qwen/Qwen3-27B model, then
# launches ntCode.py.
#
# How the variables are consumed:
#   utils/config.py  reads ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
#                    ANTHROPIC_BASE_URL, and LLM_PROVIDER via os.environ.
#   utils/llm.py     passes ANTHROPIC_BASE_URL to the Anthropic() client
#                    and uses ANTHROPIC_MODEL / MAX_TOKENS for every call.
#
# NOTE: llama.cpp speaks the OpenAI REST API (/v1/chat/completions), while
# the anthropic SDK targets /v1/messages with its own request format.
# Pointing ANTHROPIC_BASE_URL at the llama.cpp server therefore requires
# a thin compatibility proxy (e.g. LiteLLM, llama-cpp-python's built-in
# OpenAI server, or any openai-to-anthropic shim) running in front of it.
# The variables below are correct; add a proxy if you do not have one yet.
# ---------------------------------------------------------------------------

# ----- llama.cpp server ----------------------------------------------------
export LLAMA_CPP_HOST="nt-angband.local"
export LLAMA_CPP_PORT="8080"

# ----- Variables read directly by utils/config.py and utils/llm.py ---------

# Model name as advertised by the llama.cpp server
export ANTHROPIC_MODEL="Qwen/Qwen3-27B"

# Redirect the Anthropic SDK to the local llama.cpp instance.
# The SDK constructs the full endpoint as:  <ANTHROPIC_BASE_URL>/v1/messages
export ANTHROPIC_BASE_URL="http://${LLAMA_CPP_HOST}:${LLAMA_CPP_PORT}"

# A non-empty key is required so the SDK initialises without error;
# llama.cpp itself does not validate it.
export ANTHROPIC_API_KEY="llama-cpp-no-key"

# Tell the application which LLM backend is in use
export LLM_PROVIDER="llama.cpp"

# Optional tuning — increase if the model supports a larger context window
export MAX_TOKENS="8192"

# Keep rate-limit guards relaxed for a local server
export REQUESTS_PER_MINUTE="200"
export TOKENS_PER_MINUTE="500000"

# ---------------------------------------------------------------------------
echo "=========================================================="
echo " ntCode — llama.cpp backend on ${LLAMA_CPP_HOST}"
echo "=========================================================="
echo "  Base URL : ${ANTHROPIC_BASE_URL}"
echo "  Model    : ${ANTHROPIC_MODEL}"
echo "  Provider : ${LLM_PROVIDER}"
echo "=========================================================="
echo ""

exec python3 ntCode.py "$@"
