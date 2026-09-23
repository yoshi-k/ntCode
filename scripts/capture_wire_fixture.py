#!/usr/bin/env python3
"""Capture a real provider response as a wire-contract fixture.

Sends one native tool-calling request (a single ``read_file`` tool, and a
prompt asking the model to use it) straight over HTTP, then writes the raw
response as a ``kind: "response"`` fixture.  ``expect_result`` is pre-filled
from what the server actually returned, so review it before relying on it.

Examples::

    # llama.cpp (start llama-server with --jinja so it parses tool calls)
    python scripts/capture_wire_fixture.py --provider openai \\
        --base-url http://192.168.2.126:8080/v1 \\
        --model gemma-4-26B-A4B-it-UD-Q8_K_XL.gguf --name llamacpp_gemma4

    # Anthropic (reads ANTHROPIC_API_KEY)
    python scripts/capture_wire_fixture.py --provider anthropic \\
        --model claude-sonnet-4-6 --name claude_sonnet

Fixtures are written to tests/fixtures/wire/captured/, which the test suite
does not load.  Move one into tests/fixtures/wire/ once you have checked it.
Only the raw response is saved: no API key or request headers are written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "wire" / "captured"

READ_FILE = {
    "name": "read_file",
    "description": "Read a UTF-8 text file from the workspace.",
    "parameters": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Path relative to the repository root."}
        },
        "required": ["filename"],
    },
}
PROMPT = "Use the read_file tool to read README.md. Do not answer from memory."
SYSTEM = "You are ntCode, a coding assistant. Use tools when they help."


def _anthropic(args: argparse.Namespace) -> tuple[str, Dict[str, Any]]:
    key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        sys.exit("Set ANTHROPIC_API_KEY or pass --api-key.")
    body = {
        "model": args.model,
        "max_tokens": 1024,
        "system": SYSTEM,
        "tools": [{"name": READ_FILE["name"], "description": READ_FILE["description"],
                   "input_schema": READ_FILE["parameters"]}],
        "messages": [{"role": "user", "content": PROMPT}],
    }
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    base = (args.base_url or "https://api.anthropic.com").rstrip("/")
    url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    return url, _post(url, headers, body, args.timeout)


def _openai(args: argparse.Namespace) -> tuple[str, Dict[str, Any]]:
    if not args.base_url:
        sys.exit("--base-url is required for --provider openai (e.g. http://localhost:8080/v1).")
    key = args.api_key or os.environ.get("OPENAI_API_KEY", "none")
    body = {
        "model": args.model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": PROMPT}],
        "tools": [{"type": "function", "function": READ_FILE}],
        "tool_choice": "auto",
    }
    headers = {"Authorization": f"Bearer {key}"}
    url = args.base_url.rstrip("/") + "/chat/completions"
    return url, _post(url, headers, body, args.timeout)


def _post(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    resp = httpx.post(url, headers=headers, json=body, timeout=timeout)
    if resp.status_code != 200:
        sys.exit(f"HTTP {resp.status_code} from {url}:\n{resp.text[:2000]}")
    return resp.json()


def _expect_from(provider: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """What the server returned, in the fixture's expect_result format."""
    texts: List[str] = []
    calls: List[Dict[str, Any]] = []
    if provider == "anthropic":
        for block in raw.get("content", []):
            if block.get("type") == "text":
                texts.append(block["text"])
            elif block.get("type") == "tool_use":
                calls.append({"id": block["id"], "name": block["name"], "args": block["input"]})
    else:
        message = raw["choices"][0]["message"]
        texts.append(message.get("content") or "")
        for tc in message.get("tool_calls") or []:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparsed_arguments": fn.get("arguments")}
            calls.append({"id": tc.get("id"), "name": fn["name"], "args": args})
    return {"text": "".join(texts), "tool_calls": calls}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["openai", "anthropic"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", required=True, help="fixture file name, without .json")
    parser.add_argument("--base-url", default="", help="API root; for openai include /v1")
    parser.add_argument("--api-key", default="", help="defaults to ANTHROPIC_API_KEY / OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    url, raw = (_anthropic if args.provider == "anthropic" else _openai)(args)
    expect = _expect_from(args.provider, raw)

    fixture = {
        "kind": "response",
        "description": f"Captured from {args.model} at {url}. Review expect_result before use.",
        "profile": {"provider": args.provider, "model": args.model, "tool_mode": "native"},
        "tools": [READ_FILE],
        "messages": [{"role": "user", "content": [{"type": "text", "text": PROMPT}]}],
        "raw_response": raw,
        "expect_result": expect,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{args.name}.json"
    out.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Wrote {out}")
    if expect["tool_calls"]:
        print(f"Server returned {len(expect['tool_calls'])} structured tool call(s):")
        for c in expect["tool_calls"]:
            print(f"  {c['name']}({json.dumps(c['args'])})  id={c['id']!r}")
    else:
        print("Server returned NO structured tool calls. Reply text:")
        print("  " + (expect["text"][:500] or "(empty)").replace("\n", "\n  "))
        if args.provider == "openai":
            print("For llama.cpp, check that llama-server was started with --jinja;"
                  " for vLLM, with --enable-auto-tool-choice --tool-call-parser <name>.")


if __name__ == "__main__":
    main()
