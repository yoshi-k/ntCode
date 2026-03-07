import json
from typing import Any, Dict, List, Tuple

from utils.config import (
    DEBUG_MODE,
    VERBOSE_MODE,
    MAX_CONVERSATION_LENGTH,
    YOU_COLOR,
    ASSISTANT_COLOR,
    RESET_COLOR,
    logger,
)
from utils.llm import execute_llm_call
from tools.registry import TOOL_REGISTRY, get_full_system_prompt, execute_tool_safely


def extract_tool_invocations(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Return list of (tool_name, args) requested in 'tool: name({...}) lines.
    The parser expects single-line, compact JSON in the parentheses.
    """
    invocations = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("tool:"):
            continue
        try:
            after = line[len("tool:"):].strip()
            if "(" not in after:
                logger.warning(
                    f"Invalid tool invocation format (missing parentheses): {line}"
                )
                continue

            name, rest = after.split("(", 1)
            name = name.strip()

            if not name:
                logger.warning(
                    f"Invalid tool invocation format (empty tool name): {line}"
                )
                continue

            if not rest.endswith(")"):
                logger.warning(
                    f"Invalid tool invocation format (missing closing parenthesis): {line}"
                )
                continue

            json_str = rest[:-1].strip()

            # Handle empty JSON case
            if not json_str:
                args = {}
            else:
                try:
                    args = json.loads(json_str)
                    # Validate that args is a dictionary
                    if not isinstance(args, dict):
                        logger.warning(
                            f"Tool arguments must be a dictionary, got {type(args).__name__}: {line}"
                        )
                        continue
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Invalid JSON in tool invocation: {json_str} - Error: {str(e)}"
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f"Unexpected error parsing JSON in tool invocation: {json_str} - Error: {str(e)}"
                    )
                    continue

            # Validate tool name exists
            if name not in TOOL_REGISTRY:
                logger.warning(f"Unknown tool name: {name}")
                continue

            invocations.append((name, args))
            logger.debug(
                f"Successfully parsed tool invocation: {name} with args {args}"
            )

        except ValueError as e:
            logger.warning(
                f"Error parsing tool invocation format: {line} - Error: {str(e)}"
            )
            continue
        except Exception as e:
            logger.warning(
                f"Unexpected error parsing tool invocation: {line} - Error: {str(e)}"
            )
            continue

    if DEBUG_MODE and invocations:
        logger.debug(
            f"Extracted {len(invocations)} tool invocations: {[name for name, _ in invocations]}"
        )

    return invocations


def run_coding_agent_loop():
    if DEBUG_MODE:
        print("=== ntCode AI Assistant ===\n")
        print("Available tools:", ", ".join(TOOL_REGISTRY.keys()))
        print(f"Debug Mode: {DEBUG_MODE}, Verbose Mode: {VERBOSE_MODE}")
        print(f"Logging: {logger.handlers}\n")
    else:
        print("ntCode AI Assistant - Ready!\n")

    conversation = [{"role": "system", "content": get_full_system_prompt()}]

    while True:
        try:
            user_input = input(f"{YOU_COLOR}You:{RESET_COLOR}:")
        except (KeyboardInterrupt, EOFError):
            break
        conversation.append({"role": "user", "content": user_input.strip()})
        while True:
            try:
                # Prune conversation if it grows too long.
                # Always preserve index 0 (system prompt) and prune the middle.
                non_system = [m for m in conversation if m["role"] != "system"]
                if len(non_system) > MAX_CONVERSATION_LENGTH:
                    logger.info(
                        f"Conversation too long ({len(non_system)} messages), "
                        f"pruning to last {MAX_CONVERSATION_LENGTH}"
                    )
                    system_msgs = [m for m in conversation if m["role"] == "system"]
                    conversation = system_msgs + non_system[-MAX_CONVERSATION_LENGTH:]

                assistant_response = execute_llm_call(conversation)

                # Check if we got an error message instead of normal response
                if isinstance(assistant_response, str) and (
                    assistant_response.startswith("\u23f1\ufe0f")
                    or assistant_response.startswith("\U0001f6ab")
                    or assistant_response.startswith("\U0001f310")
                    or assistant_response.startswith("\U0001f511")
                    or assistant_response.startswith("\u274c")
                    or assistant_response.startswith("\U0001f4a5")
                ):
                    print(f"{ASSISTANT_COLOR}Error:{RESET_COLOR} {assistant_response}")
                    break

                tool_invocations = extract_tool_invocations(assistant_response)

                if DEBUG_MODE:
                    print(f"Assistant Response:\n {assistant_response}\n")
                    print(f"tool invocations:\n {tool_invocations}\n")

                if VERBOSE_MODE and tool_invocations:
                    print(
                        f"\nFound {len(tool_invocations)} tool invocation(s): {[name for name, _ in tool_invocations]}"
                    )
                    confirm = input("Execute these tools? (y/N): ").lower().strip()
                    if confirm not in ["y", "yes"]:
                        print("Tool execution cancelled by user.")
                        conversation.append(
                            {"role": "assistant", "content": assistant_response}
                        )
                        break

                if not tool_invocations:
                    print(
                        f"{ASSISTANT_COLOR}Assistant:{RESET_COLOR} {assistant_response}"
                    )
                    conversation.append(
                        {"role": "assistant", "content": assistant_response}
                    )
                    break

                # Record assistant's tool-call message in conversation history
                # before appending tool results, so Claude sees its own tool
                # invocation in context and doesn't duplicate it.
                conversation.append(
                    {"role": "assistant", "content": assistant_response}
                )

                # Execute tools with improved error handling
                for name, args in tool_invocations:
                    if name not in TOOL_REGISTRY:
                        logger.error(f"Unknown tool: {name}")
                        continue

                    tool = TOOL_REGISTRY[name]
                    try:
                        if DEBUG_MODE:
                            print(f"Executing tool: {name} with args: {args}")

                        # Execute tool with dynamic parameter mapping
                        resp = execute_tool_safely(name, tool, args)

                        if DEBUG_MODE:
                            print(f"Tool result: {resp}")

                        # Add tool result to conversation
                        conversation.append(
                            {
                                "role": "user",
                                "content": f"tool_result({json.dumps(resp, ensure_ascii=False)})",
                            }
                        )

                    except Exception as e:
                        logger.error(f"Tool execution failed for {name}: {str(e)}")
                        error_result = {
                            "error": f"Tool execution failed: {str(e)}",
                            "tool_name": name,
                            "success": False,
                        }
                        conversation.append(
                            {
                                "role": "user",
                                "content": f"tool_result({json.dumps(error_result)})",
                            }
                        )

            except Exception as e:
                logger.error(f"Assistant loop error: {str(e)}")
                print(f"{ASSISTANT_COLOR}Error:{RESET_COLOR} {str(e)}")
                print("Please try again with a shorter or simpler request.")
                break
