from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
)

from bot.core.i18n import i18n
from bot.core.logger import get_logger

logger = get_logger(__name__)


def _build_commands(locale: str, is_admin: bool) -> list[BotCommand]:
    """Build command list for given locale and admin status.

    Args:
        locale: Language code
        is_admin: Whether user is admin

    Returns:
        List of BotCommand objects
    """
    user_commands = [
        BotCommand(
            command="start",
            description=i18n.gettext("cmd-start-desc", locale=locale),
        ),
        BotCommand(
            command="channels",
            description=i18n.gettext("cmd-channels-desc", locale=locale),
        ),
        BotCommand(
            command="language",
            description=i18n.gettext("cmd-language-desc", locale=locale),
        ),
    ]

    if not is_admin:
        return user_commands

    admin_commands = [
        *user_commands,
        BotCommand(
            command="admin_policies",
            description=i18n.gettext("cmd-admin-policies-desc", locale=locale),
        ),
        BotCommand(
            command="admin_policy_create",
            description=i18n.gettext("cmd-admin-policy-create-desc", locale=locale),
        ),
        BotCommand(
            command="admin_policy_view",
            description=i18n.gettext("cmd-admin-policy-view-desc", locale=locale),
        ),
        BotCommand(
            command="admin_policy_add_required",
            description=i18n.gettext("cmd-admin-policy-add-required-desc", locale=locale),
        ),
        BotCommand(
            command="admin_channel_remove",
            description=i18n.gettext("cmd-admin-channel-remove-desc", locale=locale),
        ),
        BotCommand(
            command="admin_compliance_scan",
            description=i18n.gettext("cmd-admin-compliance-scan-desc", locale=locale),
        ),
        BotCommand(
            command="broadcast",
            description=i18n.gettext("cmd-broadcast-desc", locale=locale),
        ),
        BotCommand(
            command="admin_users",
            description=i18n.gettext("cmd-admin-users-desc", locale=locale),
        ),
        BotCommand(
            command="admin_user_sync",
            description=i18n.gettext("cmd-admin-user-sync-desc", locale=locale),
        ),
    ]
    return admin_commands


async def setup_bot_commands(bot: Bot) -> None:
    """Set up bot commands for the menu with default locale.

    Note: Only logs initialization. Actual commands are set per-user
    via set_user_commands() to preserve user-specific locales.

    Args:
        bot: Bot instance
    """
    logger.info("bot_commands_setup_initialized")


async def set_user_commands(
    bot: Bot, user_id: int, language_code: str, is_admin: bool = False
) -> None:
    """Set localized commands for a specific user.

    Args:
        bot: Bot instance
        user_id: User ID
        language_code: User's preferred language
        is_admin: Whether user is admin
    """
    commands = _build_commands(language_code, is_admin)

    try:
        await bot.set_my_commands(
            commands,
            scope=BotCommandScopeChat(chat_id=user_id),
        )
    except Exception as e:
        logger.warning("failed_to_set_user_commands", user_id=user_id, error=str(e))

    logger.debug(
        "user_commands_set", user_id=user_id, language=language_code, is_admin=is_admin
    )
