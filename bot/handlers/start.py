from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.i18n.core import I18n

from bot.core.db import db_manager
from bot.core.logger import get_logger
from bot.keyboards.inline.language import language_selection_keyboard
from bot.keyboards.inline.main_menu import main_menu_keyboard
from bot.services.user_service import UserService

logger = get_logger(__name__)

router = Router()


@router.message(CommandStart())
async def start_command(
    message: Message, bot: Bot, state: FSMContext, i18n: I18n
) -> None:
    """Handle /start command.

    Args:
        message: Incoming message
        bot: Bot instance
        state: FSM context
        i18n: I18n instance
    """
    user = message.from_user

    if not user:
        return

    await state.clear()

    async with db_manager.session() as session:
        user_service = UserService(session)

        profile = await user_service.upsert_profile(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
        )
        if profile.preferred_language:
            await message.answer(
                i18n.gettext("menu-welcome"),
                reply_markup=main_menu_keyboard(i18n),
            )
        else:
            await message.answer(
                i18n.gettext("language-selection"),
                reply_markup=language_selection_keyboard(),
            )

    logger.info("start_command_processed", user_id=user.id)
