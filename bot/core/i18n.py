from pathlib import Path

from aiogram.utils.i18n import I18n

from bot.config.settings import settings
from bot.core.logger import get_logger

logger = get_logger(__name__)

LOCALES_DIR = Path(__file__).parent.parent / "locales"

SUPPORTED_LANGUAGES = ["ru", "en", "ua"]

i18n = I18n(path=LOCALES_DIR, default_locale=settings.DEFAULT_LANG, domain="messages")

logger.info(
    "i18n_initialized",
    available_locales=list(i18n.locales.keys()),
    default_locale=settings.DEFAULT_LANG,
)


def get_i18n() -> I18n:
    return i18n


def _(key: str, locale: str | None = None, **kwargs) -> str:
    if locale:
        return i18n.gettext(key, locale=locale, **kwargs)
    return i18n.gettext(key, **kwargs)


logger.info(
    "i18n_initialized",
    locales_dir=str(LOCALES_DIR),
    default_locale=settings.DEFAULT_LANG,
)
