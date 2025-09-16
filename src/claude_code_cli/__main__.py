from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict
from typing import Any, Callable

from claude_code_sdk import (
    AssistantMessage,
    ClaudeCodeOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
    create_sdk_mcp_server,
    tool,
)

from .braintrust_logging import (
    BraintrustLoggingContext,
    MissingBraintrustConfig,
    configure_logging_from_env,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-code-cli",
        description="Interact with Claude Code via the Python SDK",
    )

    subparsers = parser.add_subparsers(dest="command")

    query_parser = subparsers.add_parser(
        "query", help="Run a one-off prompt using the Claude Code query helper"
    )
    query_parser.add_argument("prompt", help="Prompt to send to Claude Code")
    query_parser.add_argument(
        "--system",
        dest="system_prompt",
        help="Optional system prompt to prepend",
    )
    query_parser.add_argument(
        "--model",
        dest="model",
        help="Model identifier to use (falls back to Claude Code default)",
    )
    query_parser.add_argument(
        "--allow-tool",
        dest="allowed_tools",
        action="append",
        default=[],
        help="Allow Claude Code to call a specific tool (repeat for multiple)",
    )
    query_parser.add_argument(
        "--permission-mode",
        choices=["default", "acceptEdits", "bypassPermissions", "plan"],
        dest="permission_mode",
        help="Set the Claude Code permission mode",
    )
    query_parser.add_argument(
        "--cwd",
        dest="cwd",
        help="Working directory to expose to Claude Code",
    )
    query_parser.add_argument(
        "--max-turns",
        type=int,
        dest="max_turns",
        help="Maximum number of turns before stopping",
    )
    query_parser.set_defaults(func=run_basic_query)

    demo_parser = subparsers.add_parser(
        "demo-tools",
        help="Start a session that exposes sample tools implemented in Python",
    )
    demo_parser.add_argument(
        "--prompt",
        default=(
            "Demonstrate the available tools. Greet our sample user 'Casey', "
            "fetch their open invoices, and summarize the results."
        ),
        help="Prompt to send to Claude to drive the demo tool calls",
    )
    demo_parser.add_argument(
        "--max-turns",
        type=int,
        default=4,
        help="Maximum turns Claude Code can take during the demo session",
    )
    demo_parser.set_defaults(func=run_demo_tools)

    return parser


def ensure_api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Export your Claude API key before running."
        )
    return api_key


def ensure_command_selected(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)


def log_event(logger: logging.Logger, event_type: str, payload: dict[str, Any]) -> None:
    logger.info(event_type, extra={"event_type": event_type, "payload": payload})


def pretty_json(data: Any) -> str:
    try:
        return json.dumps(data, indent=2, sort_keys=True)
    except TypeError:
        return str(data)


def sanitize_content(block: Any) -> Any:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, SystemMessage):
        return {"type": "system", "subtype": block.subtype, "data": block.data}
    if isinstance(block, ResultMessage):
        return asdict(block)
    return str(block)


async def run_basic_query(args: argparse.Namespace, logger: logging.Logger) -> None:
    ensure_api_key()

    options = ClaudeCodeOptions()
    options.allowed_tools = list(args.allowed_tools or [])
    options.system_prompt = args.system_prompt
    options.model = args.model
    options.permission_mode = args.permission_mode
    options.cwd = args.cwd
    options.max_turns = args.max_turns

    log_event(
        logger,
        "query.start",
        {
            "allowed_tools": options.allowed_tools,
            "model": options.model,
            "permission_mode": options.permission_mode,
        },
    )

    async for message in query(prompt=args.prompt, options=options):
        await handle_message(message, logger)

    log_event(logger, "query.complete", {"prompt": args.prompt[:120]})


async def run_demo_tools(args: argparse.Namespace, logger: logging.Logger) -> None:
    ensure_api_key()

    # Sample data to return from the demo tools
    sample_user = {
        "id": "casey-123",
        "name": "Casey Doe",
        "preferred_language": "en",
        "tier": "pro",
    }
    open_invoices = [
        {"id": "INV-001", "amount": 1200.0, "status": "due", "due_date": "2024-09-15"},
        {"id": "INV-002", "amount": 580.5, "status": "overdue", "due_date": "2024-07-30"},
    ]

    @tool("lookup_user_profile", "Fetch a customer profile by identifier", {"user_id": str})
    async def lookup_user_profile(args: dict[str, Any]) -> dict[str, Any]:
        user_id = args.get("user_id")
        log_event(logger, "tool.lookup_user_profile", {"user_id": user_id})
        if user_id and user_id != sample_user["id"]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"No customer found for id '{user_id}'.",
                    }
                ],
                "is_error": True,
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": pretty_json(sample_user),
                }
            ]
        }

    @tool("list_open_invoices", "Return invoices that still require payment", {"user_id": str})
    async def list_open_invoices(args: dict[str, Any]) -> dict[str, Any]:
        user_id = args.get("user_id")
        log_event(logger, "tool.list_open_invoices", {"user_id": user_id})
        if user_id and user_id != sample_user["id"]:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"No open invoices for customer '{user_id}'.",
                    }
                ]
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": pretty_json(open_invoices),
                }
            ]
        }

    @tool(
        "generate_finance_summary",
        "Compose a finance summary that can be shared with stakeholders",
        {"user_id": str, "focus": str},
    )
    async def generate_finance_summary(args: dict[str, Any]) -> dict[str, Any]:
        log_event(logger, "tool.generate_finance_summary", {"args": args})
        total_due = sum(item["amount"] for item in open_invoices)
        summary = (
            f"Customer {sample_user['name']} currently owes ${total_due:,.2f} across "
            f"{len(open_invoices)} invoices. The most urgent item is invoice "
            f"{open_invoices[-1]['id']} which is marked overdue."
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": summary,
                }
            ]
        }

    server_name = "demo"
    server = create_sdk_mcp_server(
        name=server_name,
        tools=[lookup_user_profile, list_open_invoices, generate_finance_summary],
    )

    allowed_tools = [
        f"mcp__{server_name}__lookup_user_profile",
        f"mcp__{server_name}__list_open_invoices",
        f"mcp__{server_name}__generate_finance_summary",
    ]

    options = ClaudeCodeOptions(
        allowed_tools=allowed_tools,
        mcp_servers={server_name: server},
        permission_mode="bypassPermissions",
        max_turns=args.max_turns,
    )

    log_event(
        logger,
        "demo.start",
        {
            "prompt": args.prompt,
            "allowed_tools": allowed_tools,
            "max_turns": args.max_turns,
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(args.prompt)
        async for message in client.receive_response():
            await handle_message(message, logger)

    log_event(logger, "demo.complete", {"prompt": args.prompt[:120]})


async def handle_message(message: Any, logger: logging.Logger) -> None:
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(f"Claude: {block.text}\n")
                log_event(
                    logger,
                    "assistant.text",
                    {"model": message.model, "text": block.text},
                )
            elif isinstance(block, ToolUseBlock):
                print(
                    "[tool-call] "
                    f"{block.name} requested with input:\n{pretty_json(block.input)}\n"
                )
                log_event(
                    logger,
                    "assistant.tool_request",
                    {"tool_name": block.name, "tool_use_id": block.id},
                )
            elif isinstance(block, ToolResultBlock):
                print(
                    "[tool-result] "
                    f"Result for {block.tool_use_id}:\n{pretty_json(block.content)}\n"
                )
                log_event(
                    logger,
                    "assistant.tool_result",
                    {
                        "tool_use_id": block.tool_use_id,
                        "is_error": block.is_error,
                    },
                )
    elif isinstance(message, SystemMessage):
        print(f"[system:{message.subtype}] {message.data}\n")
        log_event(
            logger,
            "system.message",
            {"subtype": message.subtype, "data": message.data},
        )
    elif isinstance(message, ResultMessage):
        print(
            "[result] session complete — "
            f"duration={message.duration_ms}ms cost={message.total_cost_usd}\n"
        )
        log_event(
            logger,
            "result.summary",
            {
                "duration_ms": message.duration_ms,
                "api_duration_ms": message.duration_api_ms,
                "total_cost_usd": message.total_cost_usd,
                "num_turns": message.num_turns,
            },
        )
    else:
        # Fallback for other message types (e.g. echo of user message)
        print(f"[message] {message}\n")
        log_event(logger, "message.unknown", {"value": sanitize_content(message)})


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    ensure_command_selected(parser, args)

    try:
        logging_context = configure_logging_from_env()
    except MissingBraintrustConfig as exc:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        logger = logging.getLogger("claude_code_cli")
        logger.warning("Braintrust logging disabled: %s", exc)

        logging_context = BraintrustLoggingContext(logger=logger, shutdown=lambda: None)
    except Exception as exc:  # noqa: BLE001 - ensure CLI keeps running
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        logger = logging.getLogger("claude_code_cli")
        logger.error("Failed to configure Braintrust logging", exc_info=exc)
        logging_context = BraintrustLoggingContext(logger=logger, shutdown=lambda: None)

    async_fn: Callable[[argparse.Namespace, logging.Logger], Any] = args.func

    try:
        asyncio.run(async_fn(args, logging_context.logger))
    finally:
        logging_context.shutdown()


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
