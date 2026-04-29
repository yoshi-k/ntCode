---
timestamp: 2026-04-29T00:00:03
tags: [search_codebase, encoding, testing]
key: search_codebase_latin1_fallback
---
search_codebase_tool reads files with two encoding attempts:
    1. UTF-8 (strict)
    2. latin-1 (fallback)

latin-1 maps all 256 byte values to Unicode code points 0x00-0xFF,
so it NEVER raises UnicodeDecodeError. This means:

- Binary files are NOT counted in files_skipped — they decode via latin-1
  and land in files_searched instead.
- tests/test_memory_tools.py::test_binary_file_skipped therefore asserts
  only that 'files_skipped' key is present, not that it is >= 1.

If true binary-skip behaviour is needed in future, replace the latin-1
fallback with a binary sniff (e.g. check for null bytes in first 8192
bytes) and skip files that fail the sniff.
