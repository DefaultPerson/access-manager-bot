from contextlib import suppress
from datetime import datetime
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message, User
from aiogram.utils.i18n.core import I18n
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.jobs.scheduler import BROADCAST_JOBSTORE
from bot.keyboards.inline.newsletter import InlineKeyboard
from bot.services.broadcast_runtime import get_service
from bot.utils.constants import MESSAGE_DELETE_ERRORS, MESSAGE_EDIT_ERRORS
from bot.utils.misc import DataStorage


class ANManager:
    """Aiogram Newsletter Manager with i18n support."""

    def __init__(
        self,
        apscheduler: AsyncIOScheduler,
        i18n: I18n,
        inline_keyboard: InlineKeyboard,
        data: dict[str, Any],
    ) -> None:
        self.bot: Bot = data.get("bot")
        self.user: User = data.get("event_from_user")
        self.state: FSMContext = data.get("state")

        self.apscheduler = apscheduler
        self.i18n = i18n
        self.inline_keyboard = inline_keyboard
        self.data_storage = DataStorage(self.state)

        self._data: dict[str, Any] = data

    @property
    def middleware_data(self) -> dict[str, Any]:
        return self._data

    async def return_callback(self) -> None:
        return_callback = await self.data_storage.get_data("return_callback")
        await return_callback(**self.middleware_data)

    async def update_interfaces_language(self, language_code: str) -> None:
        if language_code in self.inline_keyboard.text_buttons:
            await self.state.update_data(language_code=language_code)
            self.inline_keyboard.language_code = language_code
            return None

        raise ValueError(f"Language code '{language_code}' not in button text")

    async def newsletter_menu(
        self,
        return_callback: Callable[..., Awaitable],
    ) -> Message:
        await self.data_storage.set_data(return_callback, "return_callback")
        await self.state.update_data(page=1)
        return await self.open_newsletters_window()

    async def open_newsletters_window(self) -> Message:
        from bot.states import ANState

        state_data = await self.state.get_data()
        page, page_size = state_data.get("page", 1), 5
        items = sorted(
            [
                (job.trigger.run_date.strftime("%Y-%m-%d %H:%M"), f"id:{job.id}")
                for job in self.apscheduler.get_jobs(jobstore=BROADCAST_JOBSTORE)
                if hasattr(job.trigger, "run_date")
            ],
            key=lambda x: x[0],
        )
        page_items = items[(page - 1) * page_size : page * page_size]
        total_pages = (len(items) + page_size - 1) // page_size

        total_subscribers = await get_service().get_subscriber_count(only_active=True)
        text = self.i18n.gettext("nl-newsletters").format(total=total_subscribers)
        reply_markup = self.inline_keyboard.newsletters(page_items, page, total_pages)
        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.newsletters)
        return message

    async def open_newsletter_window(self) -> Message:
        from bot.states import ANState

        state_data = await self.state.get_data()
        job = self.apscheduler.get_job(
            job_id=state_data.get("job_id"), jobstore=BROADCAST_JOBSTORE
        )
        message_data = job.kwargs.get("message_data")
        message_obj = Message(**message_data).as_(self.bot)
        await message_obj.send_copy(
            chat_id=self.user.id,
            reply_markup=message_obj.reply_markup,
        )

        text = self.i18n.gettext("nl-newsletter")
        reply_markup = self.inline_keyboard.back_delete()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.newsletter)
        return message

    async def open_newsletter_delete_window(self) -> Message:
        from bot.states import ANState

        text = self.i18n.gettext("nl-newsletter-delete")
        reply_markup = self.inline_keyboard.back_confirm()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.newsletter_delete)
        return message

    async def open_send_message_window(self) -> Message:
        from bot.states import ANState

        text = self.i18n.gettext("nl-send-message")
        reply_markup = self.inline_keyboard.send_message()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.send_message)
        return message

    async def open_send_buttons_window(self, text: str | None = None) -> Message:
        from bot.states import ANState

        if not text:
            text = self.i18n.gettext("nl-send-buttons")
        reply_markup = self.inline_keyboard.send_buttons()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.send_buttons)
        return message

    async def open_message_preview_window(self) -> Message:
        from bot.states import ANState

        message_data = await self.data_storage.get_data("message_data")
        message_obj = Message(**message_data)
        await message_obj.send_copy(
            self.user.id,
            reply_markup=message_obj.reply_markup,
        ).as_(self.bot)

        text = self.i18n.gettext("nl-message-preview")
        reply_markup = self.inline_keyboard.back_next()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.message_preview)
        return message

    async def open_choose_options_window(self) -> Message:
        from bot.states import ANState

        text = self.i18n.gettext("nl-choose-options")
        reply_markup = self.inline_keyboard.choose_options()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.choose_options)
        return message

    async def open_confirmation_now_window(self) -> Message:
        from bot.states import ANState

        text = self.i18n.gettext("nl-confirmation-now")
        reply_markup = self.inline_keyboard.back_confirm()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.confirmation_now)
        return message

    async def open_send_datetime_window(self, text: str = None) -> Message:
        from bot.states import ANState

        if not text:
            text = self.i18n.gettext("nl-send-datetime")
        reply_markup = self.inline_keyboard.back()
        datetime_now = datetime.now()
        text = text.format(datetime_string=datetime_now.strftime("%Y-%m-%d %H:%M"))

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.send_datetime)
        return message

    async def open_confirmation_later_window(self) -> Message:
        from bot.states import ANState

        text = self.i18n.gettext("nl-confirmation-later")
        reply_markup = self.inline_keyboard.back_confirm()

        message = await self.send_message(text, reply_markup=reply_markup)
        await self.state.set_state(ANState.confirmation_later)
        return message

    async def send_message(
        self,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message:
        message = await self.bot.send_message(
            text=text,
            chat_id=self.user.id,
            reply_markup=reply_markup,
        )
        await self.delete_previous_message()
        await self.state.update_data(an_message_id=message.message_id)
        return message

    @classmethod
    async def delete_message(cls, message: Message) -> None:
        with suppress(TelegramBadRequest):
            await message.delete()

    async def delete_previous_message(self) -> Message | None:
        state_data = await self.state.get_data()
        an_message_id = state_data.get("an_message_id")
        if not an_message_id:
            return

        try:
            await self.bot.delete_message(
                message_id=an_message_id,
                chat_id=self.user.id,
            )
        except TelegramBadRequest as ex:
            if any(e in ex.message for e in MESSAGE_DELETE_ERRORS):
                try:
                    text = self.i18n.gettext("nl-outdated-text")
                    return await self.bot.edit_message_text(
                        message_id=an_message_id,
                        chat_id=self.user.id,
                        text=text,
                    )
                except TelegramBadRequest as ex:
                    if not any(e in ex.message for e in MESSAGE_EDIT_ERRORS):
                        raise ex
