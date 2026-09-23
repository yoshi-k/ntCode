"""Tests for core/tool_schema.py: the single tool-description generator."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

import pytest

from core.tool_schema import json_schema_for, tool_spec_from_function, tool_specs


@pytest.mark.parametrize("annotation, schema", [
    (str, {"type": "string"}),
    (int, {"type": "integer"}),
    (float, {"type": "number"}),
    (bool, {"type": "boolean"}),
    (List[str], {"type": "array", "items": {"type": "string"}}),
    (list[int], {"type": "array", "items": {"type": "integer"}}),
    (list, {"type": "array"}),
    (Dict[str, int], {"type": "object"}),
    (dict, {"type": "object"}),
    (Optional[str], {"type": "string"}),
    (List[str] | None, {"type": "array", "items": {"type": "string"}}),
    (Literal["a", "b"], {"enum": ["a", "b"], "type": "string"}),
])
def test_json_schema_for(annotation, schema):
    assert json_schema_for(annotation) == schema


@pytest.mark.parametrize("annotation", [bytes, int | str, object])
def test_unsupported_annotations_raise(annotation):
    with pytest.raises(TypeError):
        json_schema_for(annotation)


def _sample(path: str, tags: List[str] | None = None, limit: int = 10, force: bool = False) -> dict:
    """
    Do a sample thing.

    Second paragraph of the description,
    wrapped over two lines.

    :param path: Where to do it.
    :param tags: Optional tags,
                 continued on a second line.
    :param limit: How many.
    :return: Something.
    """


def test_spec_from_function():
    spec = tool_spec_from_function("sample", _sample)
    assert spec.name == "sample"
    assert spec.description == (
        "Do a sample thing.\n\nSecond paragraph of the description, wrapped over two lines."
    )
    assert spec.parameters == {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Where to do it."},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "Optional tags, continued on a second line."},
            "limit": {"type": "integer", "description": "How many.", "default": 10},
            "force": {"type": "boolean", "default": False},
        },
        "required": ["path"],
    }


def test_no_parameters_has_no_required_key():
    def noop() -> dict:
        """Nothing."""
    assert tool_spec_from_function("noop", noop).parameters == {"type": "object", "properties": {}}


def test_missing_annotation_raises():
    def bad(x):  # noqa: ANN001
        """Bad."""
    with pytest.raises(TypeError, match="no type annotation"):
        tool_spec_from_function("bad", bad)


def test_var_kwargs_raise():
    def bad(**kwargs: str) -> dict:
        """Bad."""
    with pytest.raises(TypeError):
        tool_spec_from_function("bad", bad)


def test_tool_specs_filters_by_allowlist():
    def a() -> dict:
        """A."""
    def b() -> dict:
        """B."""
    registry = {"a": a, "b": b}
    assert [s.name for s in tool_specs(registry)] == ["a", "b"]
    assert [s.name for s in tool_specs(registry, ["b"])] == ["b"]
    assert [s.name for s in tool_specs(registry, [])] == ["a", "b"]


def test_every_registered_tool_has_a_spec():
    from tools.registry import TOOL_REGISTRY

    specs = tool_specs(TOOL_REGISTRY)
    assert [s.name for s in specs] == list(TOOL_REGISTRY)
    for spec in specs:
        assert spec.description, f"{spec.name} has no description"
        assert spec.parameters["type"] == "object"


def test_list_parameters_are_arrays_in_native_schema():
    """Regression: git_add.file_paths (List[str]) used to be sent to OpenAI as "string"."""
    from core.types import Message
    from providers.openai_chat import OpenAIChatProvider
    from tools.registry import TOOL_REGISTRY

    request = OpenAIChatProvider("m", base_url="http://x/v1").build_request(
        "", [Message.user("hi")], tool_specs(TOOL_REGISTRY)
    )
    tools = {t["function"]["name"]: t["function"] for t in request["tools"]}
    assert tools["git_add"]["parameters"]["properties"]["file_paths"] == {
        "type": "array", "items": {"type": "string"},
        "description": "List of file paths to stage for commit",
    }
    assert tools["memory_store"]["parameters"]["properties"]["tags"]["type"] == "array"
