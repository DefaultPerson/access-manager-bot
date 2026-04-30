from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n.core import I18n

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.core.menu import set_user_commands
from bot.keyboards.inline.language import language_selection_keyboard
from bot.keyboards.inline.main_menu import main_menu_keyboard
from bot.services.user_service import UserService

logger = get_logger(__name__)

router = Router()


@router.message(Command("language"))
async def language_command(message: Message, state: FSMContext, i18n: I18n) -> None:
    """Handle /language command.

    Args:
        message: Incoming message
        state: FSM context
        i18n: I18n instance
    """
    user = message.from_user
    if not user:
        return

    await state.clear()

    await message.answer(
        i18n.gettext("language-selection"),
        reply_markup=language_selection_keyboard(),
    )
    logger.info("language_menu_shown", user_id=user.id)


@router.callback_query(F.data.startswith("lang:"))
async def language_callback(callback: CallbackQuery, bot: Bot, i18n: I18n) -> None:
    """Handle language selection callback.

    Args:
        callback: Callback query with lang:{code} data
        bot: Bot instance
    """
    user = callback.from_user
    if not user or not callback.data:
        await callback.answer("Error")
        return

    language_code = callback.data.split(":", 1)[1]

    if language_code not in ["ru", "en", "ua"]:
        await callback.answer("Invalid language")
        return

    async with db_manager.session() as session:
        user_service = UserService(session)

        await user_service.set_language(user.id, language_code)

        await callback.answer(
            i18n.gettext("language-selected", locale=language_code),
        )
        await callback.message.delete()

        await callback.message.answer(
            i18n.gettext("menu-welcome", locale=language_code),
            reply_markup=main_menu_keyboard(i18n, locale=language_code),
        )

        is_admin = user.id in settings.admin_ids_list
        await set_user_commands(bot, user.id, language_code, is_admin)

    await callback.answer()
    logger.info("language_selected", user_id=user.id, language=language_code)
