"""Provider-aware tool prompt formatters and response parsers for ntCode.

.. note:: This file has been extended with a ``gemma`` family for Gemma 3/4
   models served via llama.cpp.  See the ``gemma`` section below.

This module is the single place where model-family differences in tool-call
conventions are handled.  Everything else in the stack (ConversationManager,
execute_tool_safely, the tool files themselves) stays completely unchanged.

Two public entry points
-----------------------
format_tools_for_provider(provider, model, tool_registry)
    Returns the string that replaces {{TOOLS}} in the system prompt for the
    given provider/model combination.

get_parser_for_provider(provider, model)
    Returns a callable with signature
        (text: str) -> List[Tuple[str, Dict[str, Any]]]
    that extracts tool invocations from a model response.

Supported model families
------------------------
``ntcode``  (default)
    The original ntCode text protocol::

        tool: NAME({"key": "value"})

    Works well with Anthropic Claude and with OpenAI models (GPT-4o, etc.).

``xml``
    XML-style tool calls used by Qwen2.5-Instruct and some Mistral variants::

        <tool_call>
        {"name": "tool_name", "arguments": {"key": "value"}}
        </tool_call>

``json_block``
    Fenced JSON block, common with smaller Llama/Mistral fine-tunes::

        ```json
        {"tool": "tool_name", "args": {"key": "value"}}
        ```

``gemma``
    Gemma 3/4 instruct models (google/gemma-3-27b-it, gemma-4, etc.) emit
    tool calls wrapped in pipe-angle-bracket delimiter tokens::

        <|tool_call>call:tool:NAME({"key": "value"})<tool_call|>

    The parser also tolerates JS-style unquoted keys that the model
    sometimes produces: ``{key: "value"}``.

Adding a new format
-------------------
1.  Write a ``_format_tools_<name>()`` function that returns the tool-block
    string for the system prompt.
2.  Write a ``_parse_<name>()`` function that parses LLM output and returns
    ``List[Tuple[str, Dict]]``.
3.  Register both in ``_FORMAT_REGISTRY`` and ``_PARSER_REGISTRY``.
4.  Add the model-family detection logic in ``_detect_family()``.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable, Dict, List, Tuple

from utils.config import logger

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ToolRegistry = Dict[str, Callable]  # maps tool name -> tool function
Parser = Callable[[str], List[Tuple[str, Dict[str, Any]]]]


# ===========================================================================
# Model-family detection
# ===========================================================================

def _detect_family(provider: str, model: str) -> str:
    """Return the tool-format family name for the given provider/model pair.

    The detection is purely based on the model name string (lowercased).
    Add new patterns here when you add a new format.

    Returns one of: ``"ntcode"``, ``"xml"``, ``"json_block"``, ``"gemma"``.
    """
    m = model.lower()

    # Qwen2.5-Instruct and Qwen3 models emit <tool_call>...</tool_call> blocks
    # when prompted correctly (documented in the Qwen model cards).
    if "qwen" in m:
        return "xml"

    # Mistral-Nemo and some Mistral-7B fine-tunes use JSON blocks.
    # (Mistral-Large on the Mistral API supports function calling natively;
    #  when accessed via llama.cpp it falls back to text so we use json_block.)
    if "mistral" in m or "mixtral" in m:
        return "json_block"

    # Gemma 3/4 instruct models emit <|tool_call>call:tool:NAME({...})<tool_call|>
    # with occasional JS-style unquoted keys in the argument object.
    if "gemma" in m:
        return "gemma"

    # Everything else — Claude, GPT-*, Llama, Phi — uses the default
    # ntCode text protocol which they follow reliably when prompted.
    return "ntcode"


# ===========================================================================
# ntcode format  (default)
# ===========================================================================

def _format_tools_ntcode(tool_registry: ToolRegistry) -> str:
    """Return the {{TOOLS}} block for the ntCode text protocol.

    Example output for one tool::

        TOOL
        ===

            Name: read_file
            Description:
            Gets the full content of a file provided by the user.
            ...
            Signature: (filename: str) -> Dict[str, Any]

        ===============

    This is the original format; it is reproduced here so all formats live
    in one place and the prompt builder has a single call site.
    """
    parts: list[str] = []
    for name, fn in tool_registry.items():
        block = f"""
    Name: {name}
    Description: {fn.__doc__}
    Signature: {inspect.signature(fn)}
    """
        parts.append("TOOL\n===\n" + block)
        parts.append("=" * 15)
    return "\n".join(parts)


_NTCODE_LINE_RE = re.compile(
    r"^tool:\s*(\w+)\s*\((.*)\)\s*$",
    re.DOTALL,
)


def _parse_ntcode(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Parse ``tool: NAME({...})`` lines from *text*.

    This is the original parser from ``utils/agent.py``, extracted here so it
    lives alongside its companion formatter.  The agent delegates to whichever
    parser is returned by :func:`get_parser_for_provider`.
    """
    # Import lazily to avoid a circular import at module load time.
    from tools.registry import TOOL_REGISTRY

    invocations: List[Tuple[str, Dict[str, Any]]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("tool:"):
            continue
        try:
            after = line[len("tool:"):].strip()

            if "(" not in after:
                logger.warning("[ntcode parser] Missing parentheses: %s", line)
                continue

            name, rest = after.split("(", 1)
            name = name.strip()

            if not name:
                logger.warning("[ntcode parser] Empty tool name: %s", line)
                continue

            if not rest.endswith(")"):
                logger.warning(
                    "[ntcode parser] Missing closing parenthesis: %s", line
                )
                continue

            json_str = rest[:-1].strip()

            if not json_str:
                args: Dict[str, Any] = {}
            else:
                try:
                    args = json.loads(json_str)
                    if not isinstance(args, dict):
                        logger.warning(
                            "[ntcode parser] Args must be a dict, got %s: %s",
                            type(args).__name__,
                            line,
                        )
                        continue
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[ntcode parser] Invalid JSON '%s': %s", json_str, exc
                    )
                    continue

            if name not in TOOL_REGISTRY:
                logger.warning("[ntcode parser] Unknown tool: %s", name)
                continue

            invocations.append((name, args))
            logger.debug("[ntcode parser] Parsed: %s args=%s", name, args)

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[ntcode parser] Unexpected error on '%s': %s", line, exc
            )

    return invocations


# ===========================================================================
# xml format  (Qwen2.5-Instruct, Qwen3, some Mistral fine-tunes)
# ===========================================================================

_XML_TOOL_PROMPT_HEADER = """\
You have access to the following tools. To call a tool, output ONLY the
following block and nothing else on those lines:

<tool_call>
{"name": "<tool_name>", "arguments": {"param1": "value1", "param2": "value2"}}
</tool_call>

After receiving the tool result you will get a message that starts with
"tool_result(" — continue the task from there.
Do NOT output any prose on the same lines as a tool_call block.
If no tool is needed, respond normally.

Available tools:
"""


def _format_tools_xml(tool_registry: ToolRegistry) -> str:
    """Return the {{TOOLS}} block for the XML tool-call format.

    Produces a header that explains the <tool_call> syntax followed by a
    JSON-schema-style description of each tool.
    """
    parts: list[str] = [_XML_TOOL_PROMPT_HEADER]
    for name, fn in tool_registry.items():
        sig = inspect.signature(fn)
        params: dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            ann = param.annotation
            type_str = (
                ann.__name__ if hasattr(ann, "__name__")
                else str(ann).replace("typing.", "")
            )
            entry: dict[str, Any] = {"type": type_str}
            if param.default is not inspect.Parameter.empty:
                entry["default"] = param.default
            params[pname] = entry

        schema = {
            "name": name,
            "description": (fn.__doc__ or "").strip(),
            "parameters": params,
        }
        parts.append(json.dumps(schema, indent=2))
        parts.append("-" * 40)
    return "\n".join(parts)


# Matches a <tool_call>\n{...}\n</tool_call> block; DOTALL so the JSON body
# can span multiple lines.
_XML_BLOCK_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


def _parse_xml(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Parse ``<tool_call>{...}</tool_call>`` blocks from *text*."""
    from tools.registry import TOOL_REGISTRY

    invocations: List[Tuple[str, Dict[str, Any]]] = []

    for match in _XML_BLOCK_RE.finditer(text):
        raw_json = match.group(1).strip()
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning("[xml parser] Invalid JSON in tool_call block: %s", exc)
            continue

        if not isinstance(obj, dict):
            logger.warning("[xml parser] tool_call JSON is not a dict: %r", obj)
            continue

        name = obj.get("name", "")
        if not name:
            logger.warning("[xml parser] tool_call missing 'name' field: %r", obj)
            continue

        if name not in TOOL_REGISTRY:
            logger.warning("[xml parser] Unknown tool name: %s", name)
            continue

        args = obj.get("arguments", obj.get("args", {}))
        if not isinstance(args, dict):
            logger.warning(
                "[xml parser] 'arguments' field is not a dict for tool %s: %r",
                name,
                args,
            )
            continue

        invocations.append((name, args))
        logger.debug("[xml parser] Parsed: %s args=%s", name, args)

    return invocations


# ===========================================================================
# json_block format  (Llama, smaller Mistral fine-tunes)
# ===========================================================================

_JSON_BLOCK_TOOL_PROMPT_HEADER = """\
You have access to the following tools. To call a tool, output ONLY a fenced
JSON block and nothing else on those lines:

```json
{"tool": "<tool_name>", "args": {"param1": "value1", "param2": "value2"}}
```

After receiving the tool result you will get a message starting with
"tool_result(" — continue the task from there.
Do NOT mix prose and a tool call on the same lines.
If no tool is needed, respond normally.

Available tools:
"""


def _format_tools_json_block(tool_registry: ToolRegistry) -> str:
    """Return the {{TOOLS}} block for the fenced-JSON-block format."""
    parts: list[str] = [_JSON_BLOCK_TOOL_PROMPT_HEADER]
    for name, fn in tool_registry.items():
        sig = inspect.signature(fn)
        params: dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            ann = param.annotation
            type_str = (
                ann.__name__ if hasattr(ann, "__name__")
                else str(ann).replace("typing.", "")
            )
            entry: dict[str, Any] = {"type": type_str}
            if param.default is not inspect.Parameter.empty:
                entry["default"] = param.default
            params[pname] = entry

        schema = {
            "name": name,
            "description": (fn.__doc__ or "").strip(),
            "parameters": params,
        }
        parts.append(json.dumps(schema, indent=2))
        parts.append("-" * 40)
    return "\n".join(parts)


# Matches ```json\n{...}\n``` fences; DOTALL so the body can span lines.
_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


def _parse_json_block(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Parse fenced ```json {"tool": ..., "args": {...}} ``` blocks from *text*."""
    from tools.registry import TOOL_REGISTRY

    invocations: List[Tuple[str, Dict[str, Any]]] = []

    for match in _JSON_FENCE_RE.finditer(text):
        raw_json = match.group(1).strip()
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning("[json_block parser] Invalid JSON in fenced block: %s", exc)
            continue

        if not isinstance(obj, dict):
            logger.warning("[json_block parser] Fenced JSON is not a dict: %r", obj)
            continue

        name = obj.get("tool", "")
        if not name:
            logger.warning("[json_block parser] Missing 'tool' field: %r", obj)
            continue

        if name not in TOOL_REGISTRY:
            logger.warning("[json_block parser] Unknown tool name: %s", name)
            continue

        args = obj.get("args", {})
        if not isinstance(args, dict):
            logger.warning(
                "[json_block parser] 'args' field is not a dict for tool %s: %r",
                name,
                args,
            )
            continue

        invocations.append((name, args))
        logger.debug("[json_block parser] Parsed: %s args=%s", name, args)

    return invocations


# ===========================================================================
# gemma format  (Gemma 3/4 instruct models via llama.cpp)
# ===========================================================================

_GEMMA_TOOL_PROMPT_HEADER = """\
You have access to the following tools. To call a tool, output ONLY the
following on its own line and nothing else:

<|tool_call>call:tool:TOOL_NAME({"arg": "value"})<tool_call|>

Rules:
- Replace TOOL_NAME with the exact tool name.
- Replace the JSON object with the actual arguments as strict JSON
  (keys must be double-quoted strings).
- If the tool takes no arguments use an empty object: {}.
- Output ONLY the <|tool_call>...<tool_call|> line — no prose before or after.
- After receiving a tool_result(...) message, continue the task normally.
- If no tool is needed, respond normally without the delimiter tokens.

Available tools:
"""


def _format_tools_gemma(tool_registry: ToolRegistry) -> str:
    """Return the {{TOOLS}} block for Gemma instruct models.

    Instructs the model to use its native
    ``<|tool_call>call:tool:NAME({...})<tool_call|>`` delimiter style
    with strict JSON arguments.
    """
    parts: list[str] = [_GEMMA_TOOL_PROMPT_HEADER]
    for name, fn in tool_registry.items():
        sig = inspect.signature(fn)
        params: dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            ann = param.annotation
            type_str = (
                ann.__name__ if hasattr(ann, "__name__")
                else str(ann).replace("typing.", "")
            )
            entry: dict[str, Any] = {"type": type_str}
            if param.default is not inspect.Parameter.empty:
                entry["default"] = param.default
            params[pname] = entry

        schema = {
            "name": name,
            "description": (fn.__doc__ or "").strip(),
            "parameters": params,
        }
        parts.append(json.dumps(schema, indent=2))
        parts.append("-" * 40)
    return "\n".join(parts)


# Matches <|tool_call>...<tool_call|> blocks.
# The body is everything between the two delimiter tokens.
_GEMMA_BLOCK_RE = re.compile(
    r"<\|tool_call>(.*?)<tool_call\|>",
    re.DOTALL,
)

# Matches the optional "call:tool:" prefix Gemma prepends to the tool name.
_GEMMA_PREFIX_RE = re.compile(r"^(?:call:tool:)?")


def _fix_unquoted_keys(s: str) -> str:
    """Best-effort conversion of JS-style unquoted object keys to JSON.

    Gemma sometimes emits ``{path: "."}`` instead of ``{"path": "."}``.  This
    function quotes bare identifier keys so ``json.loads`` can parse them.
    Only top-level keys are targeted; nested objects are handled recursively
    by the same regex pass over the whole string.

    The regex matches a word-character sequence that is preceded by ``{`` or
    ``,`` (with optional whitespace) and followed by ``:``, and is not already
    surrounded by double-quotes.
    """
    return re.sub(
        r'(?<=[{,])\s*(\w+)\s*:',
        lambda m: ' "' + m.group(1) + '":',
        s,
    )


def _parse_gemma(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Parse ``<|tool_call>call:tool:NAME({...})<tool_call|>`` blocks from *text*.

    Tolerates:
    - Optional ``call:tool:`` prefix before the tool name.
    - JS-style unquoted object keys (e.g. ``{path: "."}``)
      via :func:`_fix_unquoted_keys`.
    """
    from tools.registry import TOOL_REGISTRY

    invocations: List[Tuple[str, Dict[str, Any]]] = []

    for match in _GEMMA_BLOCK_RE.finditer(text):
        body = match.group(1).strip()

        # Strip optional "call:tool:" prefix.
        body = _GEMMA_PREFIX_RE.sub("", body)

        # Split on first "(" to separate tool name from args.
        if "(" not in body:
            logger.warning("[gemma parser] Missing '(' in tool_call body: %r", body)
            continue

        name, rest = body.split("(", 1)
        name = name.strip()

        if not name:
            logger.warning("[gemma parser] Empty tool name in body: %r", body)
            continue

        if name not in TOOL_REGISTRY:
            logger.warning("[gemma parser] Unknown tool name: %s", name)
            continue

        if not rest.endswith(")"):
            logger.warning("[gemma parser] Missing closing ')' in body: %r", body)
            continue

        json_str = rest[:-1].strip()

        if not json_str:
            args: Dict[str, Any] = {}
        else:
            # First attempt strict JSON; fall back to unquoted-key fixer.
            try:
                args = json.loads(json_str)
            except json.JSONDecodeError:
                fixed = _fix_unquoted_keys(json_str)
                try:
                    args = json.loads(fixed)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[gemma parser] Invalid JSON (even after key fix) '%s': %s",
                        json_str, exc,
                    )
                    continue

        if not isinstance(args, dict):
            logger.warning(
                "[gemma parser] Args must be a dict, got %s in: %r",
                type(args).__name__, body,
            )
            continue

        invocations.append((name, args))
        logger.debug("[gemma parser] Parsed: %s args=%s", name, args)

    return invocations


# ===========================================================================
# Registries and public API
# ===========================================================================

# Maps family name -> formatter function
_FORMAT_REGISTRY: Dict[str, Callable[[ToolRegistry], str]] = {
    "ntcode": _format_tools_ntcode,
    "xml": _format_tools_xml,
    "json_block": _format_tools_json_block,
    "gemma": _format_tools_gemma,
}

# Maps family name -> parser function
_PARSER_REGISTRY: Dict[str, Parser] = {
    "ntcode": _parse_ntcode,
    "xml": _parse_xml,
    "json_block": _parse_json_block,
    "gemma": _parse_gemma,
}


def format_tools_for_provider(
    provider: str,
    model: str,
    tool_registry: ToolRegistry,
) -> str:
    """Return the {{TOOLS}} replacement string for *provider* / *model*.

    Falls back to the ntcode format if the detected family is not in the
    registry (should not happen, but defensive).

    Args:
        provider:      Value of ``LLM_PROVIDER`` (``"anthropic"`` or ``"openai"``)
        model:         Model name string, e.g. ``"Qwen/Qwen3-27B"`` or
                       ``"claude-sonnet-4-6"``.
        tool_registry: The ``TOOL_REGISTRY`` dict mapping names to functions.

    Returns:
        Formatted tool-description block as a plain string.
    """
    family = _detect_family(provider, model)
    formatter = _FORMAT_REGISTRY.get(family, _FORMAT_REGISTRY["ntcode"])
    logger.info(
        "[tool_format] provider=%s model=%s -> family=%s formatter=%s",
        provider, model, family, formatter.__name__,
    )
    return formatter(tool_registry)


def get_parser_for_provider(provider: str, model: str) -> Parser:
    """Return the tool-invocation parser for *provider* / *model*.

    Args:
        provider: Value of ``LLM_PROVIDER``.
        model:    Model name string.

    Returns:
        A callable ``(text: str) -> List[Tuple[str, Dict[str, Any]]]``.
    """
    family = _detect_family(provider, model)
    parser = _PARSER_REGISTRY.get(family, _PARSER_REGISTRY["ntcode"])
    logger.info(
        "[tool_format] provider=%s model=%s -> family=%s parser=%s",
        provider, model, family, parser.__name__,
    )
    return parser
