"""Tests for the roles subsystem (utils/roles.py).

All tests are offline — no LLM calls, no API keys needed.
A temporary directory is used for TOML files so the real roles/ directory
is never touched.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_toml(path: Path, content: str) -> None:
    """Write a TOML file; creates parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


# ---------------------------------------------------------------------------
# _parse_role_dict
# ---------------------------------------------------------------------------

def test_parse_minimal_role():
    """A TOML dict with only [role].name is valid."""
    from utils.roles import _parse_role_dict
    data = {"role": {"name": "minimal"}}
    role = _parse_role_dict(data, source_path="/fake")
    assert role.name == "minimal"
    assert role.description == ""
    assert role.tools == []
    assert role.config_overrides == {}
    assert role.rag_sources == []
    assert role.system_prompt_file is None


def test_parse_missing_role_section():
    from utils.roles import _parse_role_dict
    with pytest.raises(ValueError, match="missing the required \\[role\\]"):
        _parse_role_dict({}, source_path="/fake")


def test_parse_empty_name():
    from utils.roles import _parse_role_dict
    with pytest.raises(ValueError, match="non-empty 'name'"):
        _parse_role_dict({"role": {"name": ""}}, source_path="/fake")


def test_parse_tools_list():
    from utils.roles import _parse_role_dict
    data = {"role": {"name": "r"}, "tools": ["read_file", "list_files"]}
    role = _parse_role_dict(data)
    assert role.tools == ["read_file", "list_files"]


def test_parse_tools_invalid_type():
    from utils.roles import _parse_role_dict
    with pytest.raises(ValueError, match="must be a TOML array"):
        _parse_role_dict({"role": {"name": "r"}, "tools": "read_file"})


def test_parse_config_overrides():
    from utils.roles import _parse_role_dict
    data = {
        "role": {"name": "r"},
        "config": {"OPENAI_TEMPERATURE": "0.7", "GIT_TIMEOUT": "45"},
    }
    role = _parse_role_dict(data)
    assert role.config_overrides == {"OPENAI_TEMPERATURE": "0.7", "GIT_TIMEOUT": "45"}


def test_parse_rag_sources():
    from utils.roles import _parse_role_dict
    data = {
        "role": {"name": "r"},
        "rag": {
            "sources": [
                {"type": "local_dir", "path": "knowledge/", "description": "docs"},
                {"type": "url", "url": "https://example.com"},
            ]
        },
    }
    role = _parse_role_dict(data)
    assert len(role.rag_sources) == 2
    assert role.rag_sources[0].type == "local_dir"
    assert role.rag_sources[0].path == "knowledge/"
    assert role.rag_sources[0].description == "docs"
    assert role.rag_sources[1].type == "url"
    assert role.rag_sources[1].url == "https://example.com"


def test_parse_missing_system_prompt_file_raises(tmp_path):
    from utils.roles import _parse_role_dict
    data = {
        "role": {
            "name": "r",
            "system_prompt_file": str(tmp_path / "nonexistent.md"),
        }
    }
    with pytest.raises(ValueError, match="not found"):
        _parse_role_dict(data)


def test_parse_valid_system_prompt_file(tmp_path):
    from utils.roles import _parse_role_dict
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("# Hello\n", encoding="utf-8")
    data = {"role": {"name": "r", "system_prompt_file": str(prompt_file)}}
    role = _parse_role_dict(data)
    assert role.system_prompt_file == str(prompt_file)


# ---------------------------------------------------------------------------
# RoleDefinition.allows_tool
# ---------------------------------------------------------------------------

def test_allows_tool_empty_list_means_all():
    from utils.roles import RoleDefinition
    role = RoleDefinition(name="all", tools=[])
    assert role.allows_tool("read_file") is True
    assert role.allows_tool("anything") is True


def test_allows_tool_with_allowlist():
    from utils.roles import RoleDefinition
    role = RoleDefinition(name="limited", tools=["read_file", "search_web"])
    assert role.allows_tool("read_file") is True
    assert role.allows_tool("search_web") is True
    assert role.allows_tool("edit_file") is False
    assert role.allows_tool("git_commit") is False


# ---------------------------------------------------------------------------
# list_roles
# ---------------------------------------------------------------------------

def test_list_roles_empty_dir(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    assert roles_mod.list_roles() == []


def test_list_roles_nonexistent_dir(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path / "does_not_exist")
    assert roles_mod.list_roles() == []


def test_list_roles_finds_names(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "alpha.toml", """
        [role]
        name = "alpha"
    """)
    _write_toml(tmp_path / "beta.toml", """
        [role]
        name = "beta"
    """)
    result = roles_mod.list_roles()
    assert result == ["alpha", "beta"]


def test_list_roles_skips_broken_toml(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    (tmp_path / "bad.toml").write_text("not valid [ toml", encoding="utf-8")
    _write_toml(tmp_path / "good.toml", """
        [role]
        name = "good"
    """)
    result = roles_mod.list_roles()
    assert result == ["good"]


# ---------------------------------------------------------------------------
# _resolve_role_path
# ---------------------------------------------------------------------------

def test_resolve_role_path_by_name(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "myrole.toml", "[role]\nname = 'myrole'\n")
    path = roles_mod._resolve_role_path("myRole")  # case-insensitive
    assert path.name == "myrole.toml"


def test_resolve_role_path_not_found(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        roles_mod._resolve_role_path("nonexistent")


def test_resolve_role_path_absolute(tmp_path):
    import utils.roles as roles_mod
    p = tmp_path / "custom.toml"
    _write_toml(p, "[role]\nname = 'custom'\n")
    result = roles_mod._resolve_role_path(str(p))
    assert result == p


# ---------------------------------------------------------------------------
# load_role / unload_role / is_tool_allowed / get_active_role
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_active_role():
    """Ensure every test starts and ends with no active role."""
    import utils.roles as roles_mod
    roles_mod.unload_role()  # clean slate before test
    yield
    roles_mod.unload_role()  # clean up after test


def test_load_role_activates(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "researcher.toml", """
        [role]
        name = "researcher"
        description = "Test researcher"
        tools = ["read_file", "search_web"]
    """)
    role = roles_mod.load_role("researcher")
    assert role.name == "researcher"
    assert roles_mod.get_active_role() is role


def test_is_tool_allowed_no_role():
    """Without any active role all tools are allowed."""
    import utils.roles as roles_mod
    assert roles_mod.is_tool_allowed("edit_file") is True
    assert roles_mod.is_tool_allowed("git_commit") is True


def test_is_tool_allowed_with_allowlist(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "limited.toml", """
        [role]
        name = "limited"
        tools = ["read_file"]
    """)
    roles_mod.load_role("limited")
    assert roles_mod.is_tool_allowed("read_file") is True
    assert roles_mod.is_tool_allowed("edit_file") is False
    assert roles_mod.is_tool_allowed("git_commit") is False


def test_unload_role_clears_active(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "r.toml", "[role]\nname = 'r'\n")
    roles_mod.load_role("r")
    assert roles_mod.get_active_role() is not None
    roles_mod.unload_role()
    assert roles_mod.get_active_role() is None


def test_unload_role_no_op_when_inactive():
    import utils.roles as roles_mod
    roles_mod.unload_role()  # should not raise
    assert roles_mod.get_active_role() is None


def test_load_role_restores_config_on_unload(tmp_path, monkeypatch):
    """Config overrides applied by load_role are reversed by unload_role."""
    import utils.roles as roles_mod
    from utils.config_manager import config as cfg

    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)

    original_temp = cfg.get("OPENAI_TEMPERATURE")

    _write_toml(tmp_path / "hot.toml", """
        [role]
        name = "hot"
        [config]
        OPENAI_TEMPERATURE = "1.9"
    """)
    roles_mod.load_role("hot")
    assert cfg.get("OPENAI_TEMPERATURE") == pytest.approx(1.9)

    roles_mod.unload_role()
    assert cfg.get("OPENAI_TEMPERATURE") == pytest.approx(original_temp)


def test_load_role_bad_config_raises_and_does_not_activate(tmp_path, monkeypatch):
    """A role with an invalid config override must not activate."""
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "bad.toml", """
        [role]
        name = "bad"
        [config]
        OPENAI_TEMPERATURE = "99.9"
    """)
    with pytest.raises(ValueError):
        roles_mod.load_role("bad")
    assert roles_mod.get_active_role() is None


def test_load_role_overrides_system_prompt_file(tmp_path, monkeypatch):
    """load_role sets SYSTEM_PROMPT_FILE to the role's prompt;
    unload_role restores the previous value."""
    import utils.roles as roles_mod
    import utils.config as cfg_mod
    from utils.config_manager import config as cfg

    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)

    prompt_file = tmp_path / "special.md"
    prompt_file.write_text("# Special\n{{TOOLS}}\n", encoding="utf-8")

    toml_content = (
        "[role]\n"
        f'name = "special_role"\n'
        f'system_prompt_file = "{str(prompt_file).replace(chr(92), chr(47))}"\n'
    )
    _write_toml(tmp_path / "special_role.toml", toml_content)

    original_file = cfg_mod.SYSTEM_PROMPT_FILE
    roles_mod.load_role("special_role")
    assert cfg_mod.SYSTEM_PROMPT_FILE == str(prompt_file)

    roles_mod.unload_role()
    assert cfg_mod.SYSTEM_PROMPT_FILE == original_file


# ---------------------------------------------------------------------------
# RoleDefinition.summary
# ---------------------------------------------------------------------------

def test_summary_contains_name_and_tools():
    from utils.roles import RoleDefinition
    role = RoleDefinition(
        name="test",
        description="A test role",
        tools=["read_file", "search_web"],
    )
    s = role.summary()
    assert "test" in s
    assert "read_file" in s
    assert "search_web" in s


def test_summary_all_tools_when_empty():
    from utils.roles import RoleDefinition
    role = RoleDefinition(name="dev", description="Developer")
    s = role.summary()
    assert "all" in s


# ---------------------------------------------------------------------------
# handle_role_command (frontend integration)
# ---------------------------------------------------------------------------

def test_handle_role_list_no_roles(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    from frontend.common import handle_role_command
    result = handle_role_command(["/role"])
    assert "No roles found" in result


def test_handle_role_list_shows_available(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "alpha.toml", "[role]\nname = 'alpha'\n")
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "list"])
    assert "alpha" in result


def test_handle_role_load_success(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "myrole.toml", """
        [role]
        name = "myrole"
        description = "My test role"
        tools = ["read_file"]
    """)
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "load", "myrole"])
    assert "myrole" in result
    assert "\u2705" in result  # checkmark


def test_handle_role_load_not_found(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "load", "nonexistent"])
    assert "\u274c" in result  # cross mark


def test_handle_role_load_missing_arg():
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "load"])
    assert "Usage" in result


def test_handle_role_show_no_active():
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "show"])
    assert "No role" in result


def test_handle_role_show_active(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "myrole.toml", """
        [role]
        name = "myrole"
        description = "Show me"
    """)
    roles_mod.load_role("myrole")
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "show"])
    assert "myrole" in result


def test_handle_role_unload_no_active():
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "unload"])
    assert "No role" in result


def test_handle_role_unload_active(tmp_path, monkeypatch):
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "myrole.toml", "[role]\nname = 'myrole'\n")
    roles_mod.load_role("myrole")
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "unload"])
    assert "myrole" in result
    assert "\u2705" in result
    assert roles_mod.get_active_role() is None


def test_handle_role_unknown_sub():
    from frontend.common import handle_role_command
    result = handle_role_command(["/role", "frobulate"])
    assert "Unknown" in result


# ---------------------------------------------------------------------------
# dispatch_line integration
# ---------------------------------------------------------------------------

def test_dispatch_line_role_command(tmp_path, monkeypatch):
    """dispatch_line("/role list") returns LOCAL with reply text."""
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "r.toml", "[role]\nname = 'r'\n")

    from utils.connector import Connector
    from frontend.common import dispatch_line, DispatchResult

    connector = Connector()
    outcome = dispatch_line("/role list", connector)
    connector.shutdown()

    assert outcome.result == DispatchResult.LOCAL
    assert "r" in outcome.reply


# ---------------------------------------------------------------------------
# execute_tool_safely role-based access control
# ---------------------------------------------------------------------------

def test_execute_tool_safely_blocks_disallowed_tool(tmp_path, monkeypatch):
    """execute_tool_safely returns an error dict when the tool is blocked."""
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "readonly.toml", """
        [role]
        name = "readonly"
        tools = ["read_file", "list_files"]
    """)
    roles_mod.load_role("readonly")

    from tools.registry import execute_tool_safely
    from tools.edit_file import edit_file_tool

    result = execute_tool_safely("edit_file", edit_file_tool, {})
    assert result.get("success") is False
    assert "readonly" in result.get("error", "")


def test_execute_tool_safely_allows_permitted_tool(tmp_path, monkeypatch):
    """execute_tool_safely runs through to the tool when it is allowed."""
    import utils.roles as roles_mod
    monkeypatch.setattr(roles_mod, "_ROLES_DIR", tmp_path)
    _write_toml(tmp_path / "readonly.toml", """
        [role]
        name = "readonly"
        tools = ["read_file", "list_files"]
    """)
    roles_mod.load_role("readonly")

    from tools.registry import execute_tool_safely
    from tools.list_files import list_files_tool

    # list_files on the current directory should succeed
    result = execute_tool_safely("list_files", list_files_tool, {"path": "."})
    assert "error" not in result or result.get("success") is not False
