from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any

from claude_code_sdk import ClaudeCodeOptions, query

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
    query_parser.set_defaults(func=run_basic_query)

    return parser


def ensure_api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Export it before running."
        )
    return api_key


def ensure_command_selected(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize(val) for key, val in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(val) for key, val in value.items()}
    return value

def emit(event_type: str, payload: dict[str, Any]) -> None:
    event = {"event_type": event_type, **payload}
    print(json.dumps(event, ensure_ascii=False))


async def run_basic_query(args: argparse.Namespace) -> None:
    ensure_api_key()

    options = ClaudeCodeOptions()

    emit("claude_code.user_prompt", {"prompt": args.prompt})

    async for message in query(prompt=args.prompt, options=options):
        message_dict = _serialize(message)
        event_type = message.__class__.__name__
        emit(f"stream.{event_type}", {"message": message_dict})

    emit("claude_code.session_complete", {})


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    ensure_command_selected(parser, args)

    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
