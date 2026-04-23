#!/usr/bin/env python3
"""
bootstrap_roles.py — one-time script to create the roles/ directory and
starter role files.  Run this once after installing ntCode or after a fresh
clone.  Safe to re-run (existing files are not overwritten).

Usage:
    python bootstrap_roles.py
"""
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
ROLES = ROOT / "roles"
PROMPTS = ROLES / "prompts"

ROLES.mkdir(exist_ok=True)
PROMPTS.mkdir(exist_ok=True)

FILES = {
    ROLES / "developer.toml": """\
# Developer role — full access to all tools.
[role]
name = "developer"
description = "Full-access developer role: file editing, git workflow, and web research."

[config]
OPENAI_TEMPERATURE = "0.5"
""",
    ROLES / "researcher.toml": """\
# Researcher role — web search + read-only file access.
[role]
name = "researcher"
description = "Research assistant with web access and read-only file access."
system_prompt_file = "roles/prompts/researcher.md"

tools = [
    "read_file",
    "list_files",
    "search_web",
    "read_web",
]

[config]
OPENAI_TEMPERATURE = "0.7"
""",
    ROLES / "executive.toml": """\
# Executive role — read-only access plus web research.
[role]
name = "executive"
description = "Executive assistant: read-only file access plus web research."
system_prompt_file = "roles/prompts/executive.md"

tools = [
    "read_file",
    "list_files",
    "search_web",
    "read_web",
]

[config]
OPENAI_TEMPERATURE = "0.4"
""",
    PROMPTS / "researcher.md": """\
# Research Assistant

You are a research assistant. Your purpose is to help users find, synthesise,
and summarise information from the web and from local files.

## Capabilities
- Search the web using `search_web`.
- Read web pages using `read_web`.
- Read local files using `read_file` and `list_files`.

## Constraints
- You **cannot** edit or create files.
- You **cannot** run git operations.
- Always cite sources for every factual claim.

## Tool use
{{TOOLS}}

## Style
Concise, factual, well-structured. Prefer primary sources. Quantify claims.
""",
    PROMPTS / "executive.md": """\
# Executive Assistant

You are an executive assistant providing concise, accurate summaries and
analyses to support business decision-making.

## Capabilities
- Read local files and reports using `read_file` and `list_files`.
- Research current events using `search_web` and `read_web`.

## Constraints
- You **cannot** edit or create files.
- You **cannot** run git operations or execute code.
- Keep responses brief: lead with the key insight.

## Tool use
{{TOOLS}}

## Style
Professional, concise, executive-level. Structure: headline → key points → recommendation.
""",
}

created = []
skipped = []
for path, content in FILES.items():
    if path.exists():
        skipped.append(path.name)
    else:
        path.write_text(content, encoding="utf-8")
        created.append(path.name)

print(f"Created : {created}")
print(f"Skipped : {skipped}")
print("Done.")
