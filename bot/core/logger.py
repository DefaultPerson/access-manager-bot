import logging
import sys
from typing import Any

import structlog
from aiogram import Bot

from bot.config.settings import settings


def redact_pii(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    sensitive_keys = {"username", "full_name", "phone_number", "email"}

    def _redact_str(s: str) -> str:
        for k in sensitive_keys:
            s = s.replace(f"{k}=", f"{k}=[REDACTED]")
        return s

    def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for k, v in d.items():
            if k in sensitive_keys:
                out[k] = "[REDACTED]"
            elif isinstance(v, dict):
                out[k] = _redact_dict(v)
            elif k == "event" and isinstance(v, str):
                out[k] = _redact_str(v)
            else:
                out[k] = v
        return out

    return _redact_dict(event_dict)


def configure_logging() -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    renderer = (
        structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            timestamper,
            redact_pii,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logging.basicConfig(
        level=settings.LOG_LEVEL,
        handlers=[handler],
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            timestamper,
            redact_pii,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    for name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        lg.handlers.clear()
        lg.propagate = True


async def send_to_telegram(bot: Bot, message: str, level: str = "INFO") -> None:
    try:
        emoji_map = {
            "DEBUG": "🐛",
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "CRITICAL": "🚨",
        }
        emoji = emoji_map.get(level, "📝")
        formatted = f"{emoji} <b>{level}</b>\n{message}"
        await bot.send_message(
            chat_id=settings.LOG_CHAT_ID,
            text=formatted,
            message_thread_id=settings.LOG_THREAD_ID,
            parse_mode="HTML",
        )
    except Exception as e:
        structlog.get_logger().warning("telegram_log_failed", error=str(e))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


configure_logging()
logger = get_logger(__name__)
