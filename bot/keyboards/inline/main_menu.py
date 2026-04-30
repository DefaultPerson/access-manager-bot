from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n.core import I18n

from bot.config.settings import settings


def main_menu_keyboard(i18n: I18n, locale: str | None = None) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=(
                    i18n.gettext("menu-channels", locale=locale)
                    if locale
                    else i18n.gettext("menu-channels")
                ),
                callback_data="menu:channels",
            ),
        ],
        [
            InlineKeyboardButton(
                text=(
                    i18n.gettext("menu-language", locale=locale)
                    if locale
                    else i18n.gettext("menu-language")
                ),
                callback_data="menu:language",
            ),
        ],
        [
            InlineKeyboardButton(
                text=(
                    i18n.gettext("menu-support", locale=locale)
                    if locale
                    else i18n.gettext("menu-support")
                ),
                url=settings.SUPPORT_URL,
            ),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=buttons)
