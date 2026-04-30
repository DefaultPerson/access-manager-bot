from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n.core import I18n
from aiogram.utils.keyboard import InlineKeyboardBuilder


def channel_list_keyboard(
    i18n: I18n,
    channels: list[dict],
    page: int = 1,
    total_pages: int = 1,
) -> InlineKeyboardMarkup:

    builder = InlineKeyboardBuilder()

    for channel in channels:
        display_text = (
            channel["display_name"][:10] + "..."
            if len(channel["display_name"]) > 10
            else channel["display_name"]
        )
        builder.row(
            InlineKeyboardButton(
                text=display_text, url=channel["invite_link"]
            ),
            InlineKeyboardButton(
                text=i18n.gettext("channels-check-button"),
                callback_data=f"check:{channel['policy_id']}",
            ),
            InlineKeyboardButton(
                text=i18n.gettext("channels-reqs-button"),
                callback_data=f"reqs:{channel['policy_id']}",
            ),
        )

    if total_pages > 1:
        pagination_row = []
        if page > 1:
            pagination_row.append(
                InlineKeyboardButton(
                    text=i18n.gettext("channels-pagination-prev"),
                    callback_data=f"page:{page - 1}",
                )
            )
        pagination_row.append(
            InlineKeyboardButton(
                text=f"{page}/{total_pages}", callback_data="page:current"
            )
        )
        if page < total_pages:
            pagination_row.append(
                InlineKeyboardButton(
                    text=i18n.gettext("channels-pagination-next"),
                    callback_data=f"page:{page + 1}",
                )
            )

        builder.row(*pagination_row)

    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("menu-back-button"), callback_data="menu:main"
        )
    )

    return builder.as_markup()


def requirements_keyboard(
    i18n: I18n, required_channels: list[dict], policy_id: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for channel in required_channels:
        builder.row(
            InlineKeyboardButton(
                text=f"🔗 {channel['display_name']}",
                url=channel.get(
                    "invite_link", f"https://t.me/{channel['display_name']}"
                ),
            )
        )

    # Check again button
    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("missing-channels-button"),
            callback_data=f"check:{policy_id}",
        )
    )

    return builder.as_markup()


def confirm_keyboard(i18n: I18n, policy_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("confirm-button"), callback_data=f"confirm:{policy_id}"
        )
    )
    return builder.as_markup()


def join_requirements_keyboard(
    i18n: I18n, missing_channels: list, policy_id: str, locale: str = None
) -> InlineKeyboardMarkup:
    """Build keyboard with channel links and confirm button for join requests.

    Args:
        i18n: I18n instance
        missing_channels: List of PolicyChannel objects with channel_link and display_name
        policy_id: Policy UUID string

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    for channel in missing_channels:
        builder.row(
            InlineKeyboardButton(
                text=f"🔗 {channel.display_name}",
                url=channel.channel_link,
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("confirm-button", locale=locale),
            callback_data=f"confirm:{policy_id}",
        )
    )

    return builder.as_markup()


def users_pagination_keyboard(
    i18n: I18n, page: int = 1, total_pages: int = 1
) -> InlineKeyboardMarkup:
    """Build pagination keyboard for admin users list.

    Args:
        i18n: I18n instance
        page: Current page number
        total_pages: Total number of pages

    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()

    if total_pages > 1:
        pagination_row = []
        if page > 1:
            pagination_row.append(
                InlineKeyboardButton(
                    text=i18n.gettext("channels-pagination-prev"),
                    callback_data=f"users_page:{page - 1}",
                )
            )
        pagination_row.append(
            InlineKeyboardButton(
                text=f"{page}/{total_pages}", callback_data="users_page:current"
            )
        )
        if page < total_pages:
            pagination_row.append(
                InlineKeyboardButton(
                    text=i18n.gettext("channels-pagination-next"),
                    callback_data=f"users_page:{page + 1}",
                )
            )

        builder.row(*pagination_row)

    return builder.as_markup()


def ok_dismiss_keyboard(i18n: I18n) -> InlineKeyboardMarkup:
    """Build keyboard with OK button that dismisses the message.

    Args:
        i18n: I18n instance

    Returns:
        Inline keyboard markup with OK button
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("ok-button"), callback_data="dismiss:ok"
        )
    )
    return builder.as_markup()
