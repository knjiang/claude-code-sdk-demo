"""Helpers for sending CLI telemetry to Braintrust via OTLP."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource


DEFAULT_OTLP_ENDPOINT = "https://api.braintrust.dev/otel/v1/logs"


@dataclass
class BraintrustLoggingConfig:
    """Configuration needed to export logs to Braintrust."""

    api_key: str
    project_id: str
    endpoint: str = DEFAULT_OTLP_ENDPOINT
    service_name: str = "claude-code-cli"
    service_version: str | None = None
    log_level: int = logging.INFO


@dataclass
class BraintrustLoggingContext:
    """Holds the logger and cleanup hook returned by :func:`configure_logging`."""

    logger: logging.Logger
    shutdown: Callable[[], None]


class MissingBraintrustConfig(RuntimeError):
    """Raised when the Braintrust configuration is not fully specified."""


def resolve_config_from_env() -> BraintrustLoggingConfig:
    """Build a Braintrust logging config from environment variables."""

    api_key = os.getenv("BRAINTRUST_API_KEY")
    project_id = os.getenv("BRAINTRUST_PROJECT_ID")
    endpoint = os.getenv("BRAINTRUST_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)
    service_name = os.getenv("BRAINTRUST_SERVICE_NAME", "claude-code-cli")
    service_version = os.getenv("BRAINTRUST_SERVICE_VERSION")

    if not api_key or not project_id:
        raise MissingBraintrustConfig(
            "Set BRAINTRUST_API_KEY and BRAINTRUST_PROJECT_ID to enable telemetry."
        )

    return BraintrustLoggingConfig(
        api_key=api_key,
        project_id=project_id,
        endpoint=endpoint,
        service_name=service_name,
        service_version=service_version,
    )


def configure_logging_from_env() -> BraintrustLoggingContext:
    """Configure Braintrust logging using environment variables."""

    return configure_logging(resolve_config_from_env())


def configure_logging(config: BraintrustLoggingConfig) -> BraintrustLoggingContext:
    """Configure logging that exports to Braintrust via OTLP."""

    resource_attrs = {
        "service.name": config.service_name,
        "telemetry.sdk.language": "python",
        "braintrust.project_id": config.project_id,
    }
    if config.service_version:
        resource_attrs["service.version"] = config.service_version

    resource = Resource.create(resource_attrs)

    logger_provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(
        endpoint=config.endpoint,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "x-bt-parent": f"project_id:{config.project_id}",
        },
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(logger_provider)

    braintrust_handler = LoggingHandler(level=config.log_level, logger_provider=logger_provider)
    braintrust_handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )

    # Attach both Braintrust and stdout handlers to our scoped logger.
    logger = logging.getLogger("claude_code_cli")
    logger.setLevel(config.log_level)
    logger.propagate = False

    # Ensure we only add handlers once in case configure_logging() is called multiple times.
    handler_types = {type(h) for h in logger.handlers}
    if LoggingHandler not in handler_types:
        logger.addHandler(braintrust_handler)

    # Always include a console handler for local visibility.
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(config.log_level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(console_handler)

    def _shutdown() -> None:
        """Flush telemetry and release exporter resources."""
        try:
            logger_provider.force_flush()
        finally:
            logger_provider.shutdown()

    return BraintrustLoggingContext(logger=logger, shutdown=_shutdown)
