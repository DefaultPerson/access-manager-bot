from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.i18n.core import I18n

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.keyboards.inline.language import language_selection_keyboard
from bot.keyboards.inline.main_menu import main_menu_keyboard
from bot.services.user_service import UserService

logger = get_logger(__name__)

router = Router()


@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery, state: FSMContext, i18n: I18n) -> None:
    """Handle back to main menu button.

    Args:
        callback: Callback query
        state: FSM context
        i18n: I18n instance
    """
    user = callback.from_user
    if not user:
        await callback.answer("Error")
        return

    await state.clear()

    await callback.message.edit_text(
        i18n.gettext("menu-welcome"),
        reply_markup=main_menu_keyboard(i18n),
    )

    await callback.answer()
    logger.info("menu_main_shown", user_id=user.id)


@router.callback_query(F.data == "menu:language")
async def menu_language(callback: CallbackQuery, state: FSMContext, i18n: I18n) -> None:
    """Handle language menu button.

    Args:
        callback: Callback query
        state: FSM context
    """
    user = callback.from_user
    if not user:
        await callback.answer("Error")
        return

    await state.clear()

    async with db_manager.session() as session:
        user_service = UserService(session)
        profile = await user_service.get_profile(user.id)

        locale = (
            profile.preferred_language
            if profile and profile.preferred_language
            else (
                user.language_code
                if user.language_code in ["ru", "en", "ua"]
                else settings.DEFAULT_LANG
            )
        )
    await callback.message.delete()

    await callback.answer()

    await callback.message.answer(
        i18n.gettext("language-selection", locale=locale),
        reply_markup=language_selection_keyboard(),
    )
