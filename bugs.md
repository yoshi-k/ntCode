# Known Bugs

This document tracks active bugs in LinguAPI. Before starting any work, check here to avoid duplicating effort.

## Open Bugs

- [ ] **Context overflow crash** — When running LinguAPI locally, the app crashes after 3 messages if the context is large enough. Root cause is related to context size limits not being enforced before sending to the LLM.
- [ ] **`render` crashes on empty objects** — The `render` function in `ui.py` crashes when it receives empty objects. Needs a guard clause for empty/null input.

## Resolved Bugs

_None yet._
