# Claude Code CLI Demo

A small command line interface that exercises the [Claude Code Python SDK](https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-python) and ships telemetry to Braintrust using the OTLP logging endpoint. The CLI lets you:

- run one-off prompts through `claude_code_sdk.query`
- expose in-process MCP tools implemented in Python and watch Claude call them
- stream structured events to Braintrust so you can monitor usage and tool executions

## Prerequisites

1. Python 3.10+
2. Node.js and the Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
3. API keys:
   - `ANTHROPIC_API_KEY` for Claude (needed by the Claude Code CLI that the SDK wraps)
   - `BRAINTRUST_API_KEY` and `BRAINTRUST_PROJECT_ID` for OTLP logging

Install the Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Run the commands either by adding the `src` directory to `PYTHONPATH`
(`PYTHONPATH=src python -m claude_code_cli ...`) or by installing the package in
editable mode (`pip install -e .`). Once available on the module search path you
can list commands via:

```bash
python -m claude_code_cli --help
```

### 1. Simple prompt

```bash
python -m claude_code_cli query "Generate a short changelog entry for today's work"
```

Optional flags:

- `--system` to provide a system prompt
- `--allow-tool` to allow specific built-in Claude Code tools
- `--permission-mode` to set the permission mode (e.g. `acceptEdits`)
- `--model`, `--cwd`, `--max-turns`

### 2. Demo tool calls

`demo-tools` registers three Python functions as in-process MCP tools and asks Claude to use them.

```bash
python -m claude_code_cli demo-tools
```

The command defines tools for looking up a fake customer profile, listing open invoices, and generating a finance summary. Claude will plan the interaction, call the tools, and respond with a human-readable summary. Tool requests, results, and completion metadata are all logged to Braintrust.

Use `--prompt` to customise the request and `--max-turns` to control how long the session runs.

## Braintrust Logging

Telemetry is sent via OTLP over HTTP with the following defaults (override with environment variables if required):

- Endpoint: `https://api.braintrust.dev/otel/v1/logs` or `BRAINTRUST_OTLP_ENDPOINT`
- Headers: `Authorization: Bearer <BRAINTRUST_API_KEY>` and `x-bt-parent: project_id:<BRAINTRUST_PROJECT_ID>`
- Resource attributes: `service.name` defaults to `claude-code-cli`

If the Braintrust environment variables are missing, the CLI still works and falls back to console logging.

## Monitoring & Debugging

- Logs are emitted with structured payloads so you can search by `event_type` inside Braintrust.
- Each tool call records the arguments seen by the tool and whether the result was marked as an error.
- Result messages include the turn count, API latency, and reported usage for quick health checks.

## References

- [Claude Code SDK docs](https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-python)
- [Monitoring usage](https://docs.anthropic.com/en/docs/claude-code/monitoring-usage)
- [Braintrust OTLP integration](https://www.braintrust.dev/docs/start/frameworks/opentelemetry)
