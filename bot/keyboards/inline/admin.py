from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n.core import I18n
from aiogram.utils.keyboard import InlineKeyboardBuilder


def policy_management_keyboard(
    i18n: I18n, policy_id: str, is_active: bool = True
) -> InlineKeyboardMarkup:

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-add-required"),
            callback_data=f"admin:add_required:{policy_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-list-channels"),
            callback_data=f"admin:list_channels:{policy_id}",
        ),
    )

    if is_active:
        builder.row(
            InlineKeyboardButton(
                text=i18n.gettext("admin-btn-edit-link"),
                callback_data=f"admin:edit_link:{policy_id}",
            ),
        )

    if is_active:
        builder.row(
            InlineKeyboardButton(
                text=i18n.gettext("admin-btn-deactivate"),
                callback_data=f"admin:deactivate:{policy_id}",
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=i18n.gettext("admin-btn-reactivate"),
                callback_data=f"admin:reactivate:{policy_id}",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-back-to-list"),
            callback_data="admin:policy_list",
        )
    )

    return builder.as_markup()


def broadcast_confirmation_keyboard(i18n: I18n) -> InlineKeyboardMarkup:

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-confirm"), callback_data="broadcast:confirm"
        ),
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-cancel"), callback_data="broadcast:cancel"
        ),
    )

    return builder.as_markup()


def channel_action_keyboard(
    i18n: I18n, channel_id: str, policy_id: str
) -> InlineKeyboardMarkup:

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-remove-channel"),
            callback_data=f"admin:remove_channel:{channel_id}",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=i18n.gettext("admin-btn-back"),
            callback_data=f"admin:policy:{policy_id}",
        )
    )

    return builder.as_markup()
