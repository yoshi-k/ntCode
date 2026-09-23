"""Shared pytest fixtures.

ntCode keeps runtime settings in module globals (``utils.config``, the
``ConfigManager`` singleton, the active LLM, the active role).  Tests that
call ``config.set(...)`` or load a role mutate that global state, which then
leaks into every test that runs afterwards and makes results depend on file
order.  The autouse fixture below snapshots that state before each test and
restores it afterwards.
"""

import copy
import sys

import pytest

# (module name, attribute names) snapshotted around every test.  Modules are
# looked up in sys.modules rather than imported here so that test modules can
# still set environment variables / stub packages before their first import.
_GLOBALS = [
    ("utils.llm", ["llm"]),
    ("utils.agent", ["_active_parser"]),
    ("utils.roles", ["_active_role", "_saved_config_values", "_saved_prompt_file"]),
]


@pytest.fixture(autouse=True)
def _restore_global_state():
    saved = []

    cfg = sys.modules.get("utils.config")
    if cfg is not None:
        for name in dir(cfg):
            if name.isupper():
                saved.append((cfg, name, copy.copy(getattr(cfg, name))))

    for mod_name, attrs in _GLOBALS:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for name in attrs:
            if hasattr(mod, name):
                saved.append((mod, name, copy.copy(getattr(mod, name))))

    mgr_mod = sys.modules.get("utils.config_manager")
    mgr_values = dict(mgr_mod.config._values) if mgr_mod is not None else None

    yield

    for mod, name, value in saved:
        setattr(mod, name, value)
    if mgr_values is not None:
        mgr_mod.config._values = mgr_values

    prompt = sys.modules.get("utils.prompt")
    if prompt is not None:
        prompt.invalidate_cache()
