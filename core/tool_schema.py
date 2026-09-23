"""Build :class:`~core.types.ToolSpec` objects from tool functions.

This is the only place that turns a tool's Python signature and docstring
into a description for the model.  Native providers send the resulting JSON
Schema as-is; text dialects render it into the system prompt.

Supported parameter annotations: ``str``, ``int``, ``float``, ``bool``,
``list[X]`` / ``List[X]``, ``dict`` / ``Dict[...]``, ``Literal[...]`` and
``Optional[X]`` / ``X | None``.  Anything else raises ``TypeError``, so a new
tool with an unsupported signature fails in the test suite instead of being
silently described as a string.

Descriptions come from the docstring: the text before the first ``:param``
or ``:return`` line is the tool description, and ``:param name: text``
entries describe the parameters.
"""

from __future__ import annotations

import inspect
import re
import types
import typing
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from core.types import ToolSpec

_SCALARS: Dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}

_PARAM_RE = re.compile(r"^:param\s+(\w+)\s*:(.*?)(?=^:|\Z)", re.MULTILINE | re.DOTALL)


def json_schema_for(annotation: Any) -> Dict[str, Any]:
    """Return the JSON Schema for a single parameter annotation."""
    if annotation in _SCALARS:
        return {"type": _SCALARS[annotation]}

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            # Optional[X]: whether it may be omitted is decided by the default.
            return json_schema_for(non_none[0])
        raise TypeError(f"unsupported union annotation: {annotation!r}")

    if annotation is list or origin is list:
        schema: Dict[str, Any] = {"type": "array"}
        if args:
            schema["items"] = json_schema_for(args[0])
        return schema

    if annotation is dict or origin is dict:
        return {"type": "object"}

    if origin is typing.Literal:
        schema = {"enum": list(args)}
        kinds = {type(a) for a in args}
        if len(kinds) == 1 and next(iter(kinds)) in _SCALARS:
            schema["type"] = _SCALARS[next(iter(kinds))]
        return schema

    raise TypeError(f"unsupported parameter annotation: {annotation!r}")


def _split_docstring(doc: Optional[str]) -> tuple[str, Dict[str, str]]:
    text = inspect.cleandoc(doc or "")
    params = {
        m.group(1): " ".join(m.group(2).split())
        for m in _PARAM_RE.finditer(text)
    }
    head = re.split(r"^:(?:param|return|returns|raises)\b", text, maxsplit=1, flags=re.MULTILINE)[0]
    # Keep paragraph breaks, unwrap lines within a paragraph.
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", head.strip())]
    return "\n\n".join(p for p in paragraphs if p), params


def tool_spec_from_function(name: str, fn: Callable[..., Any]) -> ToolSpec:
    """Describe *fn* as the tool *name*."""
    description, param_docs = _split_docstring(fn.__doc__)
    try:
        hints = typing.get_type_hints(fn)
    except Exception as exc:  # noqa: BLE001 - unresolvable string annotations
        raise TypeError(f"tool {name!r}: cannot resolve annotations: {exc}") from exc

    properties: Dict[str, Any] = {}
    required: List[str] = []
    for pname, param in inspect.signature(fn).parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise TypeError(f"tool {name!r}: *args / **kwargs are not supported")
        if pname not in hints:
            raise TypeError(f"tool {name!r}: parameter {pname!r} has no type annotation")
        try:
            prop = json_schema_for(hints[pname])
        except TypeError as exc:
            raise TypeError(f"tool {name!r}, parameter {pname!r}: {exc}") from None
        if pname in param_docs:
            prop["description"] = param_docs[pname]
        if param.default is inspect.Parameter.empty:
            required.append(pname)
        elif param.default is not None:
            prop["default"] = param.default
        properties[pname] = prop

    parameters: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return ToolSpec(name=name, description=description, parameters=parameters)


def tool_specs(
    registry: Mapping[str, Callable[..., Any]],
    allowed: Optional[Iterable[str]] = None,
) -> List[ToolSpec]:
    """Specs for every tool in *registry*, in registry order.

    *allowed*, when given and non-empty, limits the result to those names
    (the active role's allowlist).
    """
    allow = set(allowed) if allowed else None
    return [
        tool_spec_from_function(name, fn)
        for name, fn in registry.items()
        if allow is None or name in allow
    ]
