#!/usr/bin/env python3
"""Smoke-test: verify that the configured API key and model are reachable.

Reads ANTHROPIC_API_KEY from the environment (or .env file) and uses the
model specified by NTCODE_MODEL (defaults to DEFAULT_MODEL in config.py).
No interactive prompts — suitable for use in CI or scripted environments.

Usage:
    python test_api_key.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

import anthropic
from utils.config import DEFAULT_MODEL

model = os.environ.get("NTCODE_MODEL", DEFAULT_MODEL)
api_key = os.environ.get("ANTHROPIC_API_KEY", "")

if not api_key:
    print("❌ ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
    sys.exit(1)

client = anthropic.Anthropic(api_key=api_key)

print(f"Testing model: {model}")

try:
    message = client.messages.create(
        model=model,
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with: API key is working!"}],
    )
    print(f"✅ Success! Response: {message.content[0].text}")
except anthropic.AuthenticationError:
    print("❌ Invalid API key.")
    sys.exit(1)
except anthropic.PermissionDeniedError:
    print("❌ API key lacks permission for this model.")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1)
