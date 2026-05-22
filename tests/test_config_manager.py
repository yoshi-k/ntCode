"""Tests for utils/config_manager.py.

All tests create a fresh ConfigManager instance (not the global singleton)
so they don't bleed state into each other.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixture / helpers
# ---------------------------------------------------------------------------

def _fresh() :
    """Return a brand-new ConfigManager (bypasses the module singleton)."""
    from utils.config_manager import ConfigManager
    return ConfigManager()


# ---------------------------------------------------------------------------
# keys() / get()
# ---------------------------------------------------------------------------

def test_keys_sorted():
    cfg = _fresh()
    keys = cfg.keys()
    assert keys == sorted(keys)


def test_keys_contains_known():
    cfg = _fresh()
    for k in ("DEFAULT_MODEL", "VERBOSE_MODE", "GIT_TIMEOUT",
              "LLM_PROVIDER", "API_TIMEOUT", "MAX_FILE_SIZE",
              "CALLING_CONVENTION"):
        assert k in cfg.keys()


def test_get_known_bool():
    cfg = _fresh()
    assert isinstance(cfg.get("DEBUG_MODE"), bool)


def test_get_known_int():
    cfg = _fresh()
    assert isinstance(cfg.get("GIT_TIMEOUT"), int)


def test_get_known_float():
    cfg = _fresh()
    assert isinstance(cfg.get("API_TIMEOUT"), float)


def test_get_known_str():
    cfg = _fresh()
    assert isinstance(cfg.get("DEFAULT_MODEL"), str)


def test_get_unknown_raises_key_error():
    cfg = _fresh()
    with pytest.raises(KeyError, match="Unknown config key"):
        cfg.get("NO_SUCH_KEY")


# ---------------------------------------------------------------------------
# set() — coercion from strings (as /config set passes them)
# ---------------------------------------------------------------------------

def test_set_str_value():
    cfg = _fresh()
    cfg.set("DEFAULT_MODEL", "my-custom-model")
    assert cfg.get("DEFAULT_MODEL") == "my-custom-model"


def test_set_int_from_string():
    cfg = _fresh()
    cfg.set("GIT_TIMEOUT", "45")
    assert cfg.get("GIT_TIMEOUT") == 45
    assert isinstance(cfg.get("GIT_TIMEOUT"), int)


def test_set_float_from_string():
    cfg = _fresh()
    cfg.set("API_TIMEOUT", "300.5")
    assert cfg.get("API_TIMEOUT") == pytest.approx(300.5)
    assert isinstance(cfg.get("API_TIMEOUT"), float)


@pytest.mark.parametrize("truthy", ["true", "True", "TRUE", "1", "yes", "on"])
def test_set_bool_truthy_strings(truthy):
    cfg = _fresh()
    cfg.set("VERBOSE_MODE", truthy)
    assert cfg.get("VERBOSE_MODE") is True


@pytest.mark.parametrize("falsy", ["false", "False", "FALSE", "0", "no", "off"])
def test_set_bool_falsy_strings(falsy):
    cfg = _fresh()
    cfg.set("VERBOSE_MODE", falsy)
    assert cfg.get("VERBOSE_MODE") is False


def test_set_bool_native_true():
    cfg = _fresh()
    cfg.set("VERBOSE_MODE", True)
    assert cfg.get("VERBOSE_MODE") is True


def test_set_bool_native_false():
    cfg = _fresh()
    cfg.set("DEBUG_MODE", False)
    assert cfg.get("DEBUG_MODE") is False


def test_set_returns_confirmation_string():
    cfg = _fresh()
    result = cfg.set("GIT_TIMEOUT", "99")
    assert "GIT_TIMEOUT" in result
    assert "99" in result


def test_set_unknown_key_raises():
    cfg = _fresh()
    with pytest.raises(KeyError):
        cfg.set("DOES_NOT_EXIST", "x")


# ---------------------------------------------------------------------------
# set() — validation
# ---------------------------------------------------------------------------

def test_set_provider_valid_anthropic():
    cfg = _fresh()
    cfg.set("LLM_PROVIDER", "anthropic")
    assert cfg.get("LLM_PROVIDER") == "anthropic"


def test_set_provider_valid_openai():
    cfg = _fresh()
    cfg.set("LLM_PROVIDER", "openai")
    assert cfg.get("LLM_PROVIDER") == "openai"


def test_set_provider_invalid_raises():
    cfg = _fresh()
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        cfg.set("LLM_PROVIDER", "google")


@pytest.mark.parametrize("convention", ["", "auto", "ntcode", "xml", "json_block", "gemma"])
def test_set_calling_convention_valid(convention):
    cfg = _fresh()
    cfg.set("CALLING_CONVENTION", convention)
    assert cfg.get("CALLING_CONVENTION") == convention


def test_set_calling_convention_invalid_raises():
    cfg = _fresh()
    with pytest.raises(ValueError, match="CALLING_CONVENTION"):
        cfg.set("CALLING_CONVENTION", "trodel")


def test_set_negative_timeout_raises():
    cfg = _fresh()
    with pytest.raises(ValueError):
        cfg.set("API_TIMEOUT", "-1")


def test_set_zero_timeout_raises():
    cfg = _fresh()
    with pytest.raises(ValueError):
        cfg.set("GIT_TIMEOUT", "0")


def test_set_temperature_low_boundary():
    cfg = _fresh()
    cfg.set("OPENAI_TEMPERATURE", "0.0")
    assert cfg.get("OPENAI_TEMPERATURE") == pytest.approx(0.0)


def test_set_temperature_high_boundary():
    cfg = _fresh()
    cfg.set("OPENAI_TEMPERATURE", "2.0")
    assert cfg.get("OPENAI_TEMPERATURE") == pytest.approx(2.0)


def test_set_temperature_out_of_range_raises():
    cfg = _fresh()
    with pytest.raises(ValueError):
        cfg.set("OPENAI_TEMPERATURE", "3.0")


def test_set_empty_string_for_nonempty_key_raises():
    cfg = _fresh()
    with pytest.raises(ValueError):
        cfg.set("DEFAULT_MODEL", "")


def test_set_whitespace_only_for_nonempty_key_raises():
    cfg = _fresh()
    with pytest.raises(ValueError):
        cfg.set("DEFAULT_MODEL", "   ")


def test_set_nonneg_int_zero_ok():
    cfg = _fresh()
    cfg.set("OPENAI_MAX_TOKENS", "0")
    assert cfg.get("OPENAI_MAX_TOKENS") == 0


def test_set_nonneg_int_negative_raises():
    cfg = _fresh()
    with pytest.raises(ValueError):
        cfg.set("OPENAI_MAX_TOKENS", "-1")


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

def test_reset_single_key_restores_default():
    cfg = _fresh()
    original = cfg.get("GIT_TIMEOUT")
    cfg.set("GIT_TIMEOUT", "999")
    assert cfg.get("GIT_TIMEOUT") == 999
    cfg.reset("GIT_TIMEOUT")
    assert cfg.get("GIT_TIMEOUT") == original


def test_reset_all_restores_all_defaults():
    cfg = _fresh()
    orig_git = cfg.get("GIT_TIMEOUT")
    orig_model = cfg.get("DEFAULT_MODEL")
    cfg.set("GIT_TIMEOUT", "999")
    cfg.set("DEFAULT_MODEL", "changed")
    cfg.reset()
    assert cfg.get("GIT_TIMEOUT") == orig_git
    assert cfg.get("DEFAULT_MODEL") == orig_model


def test_reset_returns_confirmation_string():
    cfg = _fresh()
    result = cfg.reset("GIT_TIMEOUT")
    assert "GIT_TIMEOUT" in result


def test_reset_all_returns_confirmation_string():
    cfg = _fresh()
    result = cfg.reset()
    assert "reset" in result.lower()


def test_reset_unknown_key_raises():
    cfg = _fresh()
    with pytest.raises(KeyError):
        cfg.reset("NO_SUCH_KEY")


# ---------------------------------------------------------------------------
# show() / help_key()
# ---------------------------------------------------------------------------

def test_show_all_contains_section_headers():
    cfg = _fresh()
    output = cfg.show()
    assert "LLM / Provider" in output
    assert "Timeouts" in output
    assert "Debug / Logging" in output


def test_show_all_contains_all_keys():
    cfg = _fresh()
    output = cfg.show()
    for k in cfg.keys():
        assert k in output


def test_show_all_marks_changed_key():
    cfg = _fresh()
    cfg.set("GIT_TIMEOUT", "999")
    output = cfg.show()
    assert "GIT_TIMEOUT *" in output


def test_show_all_no_star_when_unchanged():
    cfg = _fresh()
    output = cfg.show()
    assert "GIT_TIMEOUT *" not in output


def test_show_single_key_contains_fields():
    cfg = _fresh()
    output = cfg.show("GIT_TIMEOUT")
    assert "GIT_TIMEOUT" in output
    assert "value" in output
    assert "default" in output
    assert "info" in output


def test_show_single_key_marks_changed():
    cfg = _fresh()
    current = cfg.get("GIT_TIMEOUT")
    # Set to a value guaranteed different from the (possibly env-overridden) default.
    cfg.set("GIT_TIMEOUT", str(current + 1))
    output = cfg.show("GIT_TIMEOUT")
    # Check for the asterisk indicating a changed value
    assert "*" in output


def test_show_single_key_no_star_when_unchanged():
    cfg = _fresh()
    output = cfg.show("GIT_TIMEOUT")
    assert "GIT_TIMEOUT *" not in output


def test_show_unknown_key_raises():
    cfg = _fresh()
    with pytest.raises(KeyError):
        cfg.show("NO_SUCH_KEY")


def test_help_key_same_as_show_key():
    cfg = _fresh()
    assert cfg.help_key("GIT_TIMEOUT") == cfg.show("GIT_TIMEOUT")


def test_sensitive_keys_are_masked(tmp_path):
    """API keys should not appear in full in /config output."""
    cfg = _fresh()
    cfg.set("ANTHROPIC_API_KEY", "sk-ant-secret12345")
    output = cfg.show()
    assert "sk-ant-secret12345" not in output
    assert "sk-a" in output   # first 4 chars visible


# ---------------------------------------------------------------------------
# save() / load() round-trip
# ---------------------------------------------------------------------------

def test_save_creates_file(tmp_path):
    cfg = _fresh()
    p = tmp_path / "cfg.json"
    result = cfg.save(str(p))
    assert p.exists()
    assert "saved" in result.lower()


def test_save_produces_valid_json(tmp_path):
    cfg = _fresh()
    p = tmp_path / "cfg.json"
    cfg.save(str(p))
    with p.open() as fh:
        data = json.load(fh)
    assert isinstance(data, dict)
    assert "GIT_TIMEOUT" in data


def test_load_applies_settings(tmp_path):
    cfg = _fresh()
    cfg.set("GIT_TIMEOUT", "77")
    p = tmp_path / "cfg.json"
    cfg.save(str(p))

    cfg2 = _fresh()
    result = cfg2.load(str(p))
    assert cfg2.get("GIT_TIMEOUT") == 77
    assert "Applied" in result


def test_round_trip_preserves_all_values(tmp_path):
    cfg = _fresh()
    cfg.set("GIT_TIMEOUT", "55")
    cfg.set("DEFAULT_MODEL", "round-trip-model")
    cfg.set("VERBOSE_MODE", "true")
    p = tmp_path / "cfg.json"
    cfg.save(str(p))

    cfg2 = _fresh()
    cfg2.load(str(p))
    assert cfg2.get("GIT_TIMEOUT") == 55
    assert cfg2.get("DEFAULT_MODEL") == "round-trip-model"
    assert cfg2.get("VERBOSE_MODE") is True


def test_load_missing_file_returns_error_string():
    cfg = _fresh()
    result = cfg.load("/nonexistent/path/cfg.json")
    assert "\u274c" in result or "not found" in result.lower()


def test_load_invalid_json_returns_error_string(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json{{{")
    cfg = _fresh()
    result = cfg.load(str(p))
    assert "\u274c" in result or "invalid" in result.lower()


def test_load_skips_unknown_keys(tmp_path):
    p = tmp_path / "cfg.json"
    data = {"GIT_TIMEOUT": 42, "UNKNOWN_KEY_XYZ": "ignored"}
    with p.open("w") as fh:
        json.dump(data, fh)
    cfg = _fresh()
    result = cfg.load(str(p))
    assert cfg.get("GIT_TIMEOUT") == 42
    assert "UNKNOWN_KEY_XYZ" in result   # reported as skipped


def test_load_reports_validation_errors(tmp_path):
    p = tmp_path / "cfg.json"
    # GIT_TIMEOUT = -1 is invalid
    data = {"GIT_TIMEOUT": -1, "DEFAULT_MODEL": "valid-model"}
    with p.open("w") as fh:
        json.dump(data, fh)
    cfg = _fresh()
    result = cfg.load(str(p))
    # valid key applied, invalid key reported as error
    assert cfg.get("DEFAULT_MODEL") == "valid-model"
    assert "Errors" in result or "error" in result.lower()


def test_save_creates_parent_dirs(tmp_path):
    cfg = _fresh()
    nested = tmp_path / "a" / "b" / "cfg.json"
    result = cfg.save(str(nested))
    assert nested.exists()
    assert "saved" in result.lower()


# ---------------------------------------------------------------------------
# _sync_to_config() — check that utils.config module constants are updated
# ---------------------------------------------------------------------------

def test_set_syncs_to_config_module():
    """After set(), the matching constant in utils.config should reflect the change."""
    import utils.config as _cfg
    cfg = _fresh()
    original = _cfg.GIT_TIMEOUT
    try:
        cfg.set("GIT_TIMEOUT", "123")
        assert _cfg.GIT_TIMEOUT == 123
    finally:
        # restore
        _cfg.GIT_TIMEOUT = original


def test_reset_syncs_to_config_module():
    import utils.config as _cfg
    cfg = _fresh()
    original = _cfg.GIT_TIMEOUT
    try:
        cfg.set("GIT_TIMEOUT", "321")
        assert _cfg.GIT_TIMEOUT == 321
        cfg.reset("GIT_TIMEOUT")
        assert _cfg.GIT_TIMEOUT == original
    finally:
        _cfg.GIT_TIMEOUT = original
