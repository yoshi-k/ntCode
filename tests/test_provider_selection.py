"""Which client ntCode builds for each setting, and rebuilding it on /config set."""

from __future__ import annotations

import pytest

import utils.llm as llm_module
from core.types import Message, OpaqueBlock, TextBlock, ToolCall, ToolResult
from frontend.common import handle_config_command
from providers.anthropic import AnthropicProvider
from providers.openai_chat import OpenAIChatProvider
from utils import config as cfg
from providers.text_tools import TextToolsProvider
from utils.prompt import NATIVE_TOOLS_NOTE, build_system_prompt
from utils.tool_format import openai_tool_mode


@pytest.fixture(autouse=True)
def _throwaway_active_client(monkeypatch):
    """switch_provider() closes the previous client; make that a throwaway so
    the session's real client (restored by conftest) stays usable."""
    class Throwaway:
        model = "throwaway"

        def close(self):
            pass

    monkeypatch.setattr(llm_module, "llm", Throwaway())


@pytest.mark.parametrize("convention, mode", [
    ("", "native"), ("auto", "native"), ("native", "native"),
    ("gemma", "text"), ("xml", "text"), ("json_block", "text"), ("ntcode", "text"),
])
def test_openai_tool_mode(convention, mode):
    cfg.CALLING_CONVENTION = convention
    assert openai_tool_mode() == mode


def test_openai_defaults_to_native_provider():
    cfg.CALLING_CONVENTION = ""
    provider = llm_module._build_openai("gemma-4", "http://localhost:8080/v1")
    assert isinstance(provider, OpenAIChatProvider)
    assert (provider.model, provider.base_url) == ("gemma-4", "http://localhost:8080/v1")


def test_text_convention_wraps_the_client_in_a_dialect():
    cfg.CALLING_CONVENTION = "gemma"
    provider = llm_module._build_openai("gemma-4", "http://x/v1")
    assert isinstance(provider, TextToolsProvider)
    assert provider.dialect.name == "gemma"
    assert isinstance(provider.inner, OpenAIChatProvider)


def test_switch_provider_to_anthropic_and_openai():
    llm_module.switch_provider("anthropic/claude-sonnet-4-6")
    assert isinstance(llm_module.llm, AnthropicProvider)
    assert (cfg.LLM_PROVIDER, cfg.DEFAULT_MODEL) == ("anthropic", "claude-sonnet-4-6")
    cfg.CALLING_CONVENTION = ""
    llm_module.switch_provider("ollama/qwen3")
    assert isinstance(llm_module.llm, OpenAIChatProvider)
    assert llm_module.llm.model == "qwen3"


def test_switch_provider_updates_the_configuration():
    """Regression: /provider replaced the client but left the configuration behind,
    so the prompt, parser and later /config changes used the old provider."""
    llm_module.switch_provider("ollama/qwen3")
    assert (cfg.LLM_PROVIDER, cfg.OPENAI_MODEL) == ("openai", "qwen3")
    assert cfg.OPENAI_BASE_URL == "http://localhost:11434/v1"
    # A later, unrelated provider setting keeps the switched-to provider.
    handle_config_command("set OPENAI_TEMPERATURE 0.2")
    assert isinstance(llm_module.llm, OpenAIChatProvider)
    assert (llm_module.llm.model, llm_module.llm.temperature) == ("qwen3", 0.2)


@pytest.mark.parametrize("alias, url", [
    ("groq", "https://api.groq.com/openai/v1"),
    ("lmstudio", "http://localhost:1234/v1"),
    ("ollama", "http://localhost:11434/v1"),
])
def test_named_aliases_use_their_own_url(alias, url):
    """Regression: every alias went to OPENAI_BASE_URL (default: local Ollama)."""
    cfg.OPENAI_BASE_URL = "http://my-llama:8080/v1"
    llm_module.switch_provider(f"{alias}/some-model")
    assert llm_module.llm.base_url == url


def test_openai_alias_keeps_the_configured_url():
    cfg.OPENAI_BASE_URL = "http://my-llama:8080/v1"
    llm_module.switch_provider("openai/gemma-4")
    assert llm_module.llm.base_url == "http://my-llama:8080/v1"


def test_config_set_default_model_rebuilds_claude():
    handle_config_command("set LLM_PROVIDER anthropic")
    handle_config_command("set DEFAULT_MODEL claude-opus-5")
    assert isinstance(llm_module.llm, AnthropicProvider)
    assert llm_module.llm.model == "claude-opus-5"


def test_role_overrides_rebuild_and_restore_the_provider(tmp_path, monkeypatch):
    from utils import roles

    (tmp_path / "local.toml").write_text(
        '[role]\nname = "local"\n\n[config]\n'
        'LLM_PROVIDER = "openai"\nOPENAI_MODEL = "role-model"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(roles, "_ROLES_DIR", tmp_path)
    handle_config_command("set LLM_PROVIDER anthropic")
    assert isinstance(llm_module.llm, AnthropicProvider)

    roles.load_role("local")
    assert isinstance(llm_module.llm, OpenAIChatProvider)
    assert llm_module.llm.model == "role-model"

    roles.unload_role()
    assert isinstance(llm_module.llm, AnthropicProvider)


def test_config_set_openai_model_rebuilds_the_client():
    """Regression: /config set OPENAI_MODEL changed the prompt but not the client."""
    handle_config_command("set LLM_PROVIDER openai")
    handle_config_command("set OPENAI_MODEL gemma-4-26B")
    assert isinstance(llm_module.llm, OpenAIChatProvider)
    assert llm_module.llm.model == "gemma-4-26B"


def test_config_set_calling_convention_switches_mode():
    handle_config_command("set LLM_PROVIDER openai")
    handle_config_command("set CALLING_CONVENTION gemma")
    assert isinstance(llm_module.llm, TextToolsProvider)
    handle_config_command("set CALLING_CONVENTION native")
    assert isinstance(llm_module.llm, OpenAIChatProvider)


def test_prompt_is_native_for_native_openai():
    cfg.LLM_PROVIDER = "openai"
    cfg.CALLING_CONVENTION = ""
    assert NATIVE_TOOLS_NOTE in build_system_prompt()
    cfg.CALLING_CONVENTION = "gemma"
    assert NATIVE_TOOLS_NOTE not in build_system_prompt()


def test_claude_history_can_continue_on_an_openai_endpoint():
    """A conversation with Claude tool calls and thinking converts cleanly."""
    history = [
        Message.user("list files"),
        Message("assistant", (OpaqueBlock("anthropic", {"type": "thinking", "thinking": "", "signature": "s"}),
                              TextBlock("Listing."), ToolCall("toolu_1", "list_files", {"path": "."}))),
        Message.tool_results([ToolResult("toolu_1", '{"files": []}')]),
        Message.assistant("Empty."),
        Message.user("thanks"),
    ]
    req = OpenAIChatProvider("m", base_url="http://x/v1").build_request("sys", history, [])
    assert [m["role"] for m in req["messages"]] == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert req["messages"][2]["tool_calls"][0]["id"] == "toolu_1"
    assert req["messages"][3]["tool_call_id"] == "toolu_1"
