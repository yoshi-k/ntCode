---
timestamp: 2026-04-29T00:00:01
tags: [testing, security, patching]
key: sandbox_patching_rule
---
utils/security.py binds ALLOWED_BASE_PATHS at import time via:
    from utils.config import ALLOWED_BASE_PATHS

Patching utils.config.ALLOWED_BASE_PATHS has NO effect at runtime because
Python already copied the reference into utils.security's namespace.

Correct pattern for any test that calls a tool touching the filesystem:
    patch("utils.security.ALLOWED_BASE_PATHS", [tmp_path])

Wrong (silently does nothing):
    patch("utils.config.ALLOWED_BASE_PATHS", [tmp_path])

This applies to ALL tool tests: read_file, edit_file, list_files,
memory_store, memory_search, memory_list, search_codebase, etc.
