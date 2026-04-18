"""Centralized loguru configuration. Called once at app startup.

Dev: pretty-printed to stderr.
Prod (ENV=prod): JSON lines to stderr for ingestion by a log aggregator.
"""

import os
import sys

from loguru import logger


def configure_logging() -> None:
    logger.remove()
    env = os.environ.get("ENV", "dev")
    if env == "prod":
        logger.add(
            sys.stderr,
            level="INFO",
            serialize=True,  # JSON output
            backtrace=False,
            diagnose=False,
        )
    else:
        logger.add(
            sys.stderr,
            level="DEBUG",
            format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> | {message}",
            backtrace=True,
            diagnose=True,
        )
    logger.info(f"Logging configured (env={env})")
