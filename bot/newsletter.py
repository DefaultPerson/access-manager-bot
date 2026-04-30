import asyncio
import uuid

from aiogram import Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message
from apscheduler.triggers.date import DateTrigger

from bot.jobs.broadcast_runner import run_broadcast
from bot.jobs.scheduler import BROADCAST_JOBSTORE
from bot.manager import ANManager
from bot.states import ANState
from bot.utils.misc import validate_datetime


class AiogramNewsletterHandlers:

    @classmethod
    async def _newsletters_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.return_callback()
            await an_manager.delete_previous_message()
        elif call.data == "add":
            await an_manager.open_send_message_window()
        elif call.data.startswith("page"):
            page = int(call.data.split(":")[1])
            await an_manager.state.update_data(page=page)
            await an_manager.open_newsletters_window()
        elif call.data.startswith("id"):
            job_id = call.data.split(":")[1]
            await an_manager.state.update_data(job_id=job_id)
            await an_manager.open_newsletter_window()

        await call.answer()

    @classmethod
    async def _newsletter_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_newsletters_window()
        elif call.data == "delete":
            await an_manager.open_newsletter_delete_window()

        await call.answer()

    @classmethod
    async def _newsletter_delete_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_newsletter_window()
        elif call.data == "confirm":
            state_data = await an_manager.state.get_data()
            an_manager.apscheduler.remove_job(
                state_data.get("job_id"),
                jobstore=BROADCAST_JOBSTORE,
            )
            await an_manager.open_newsletters_window()

        await call.answer()

    @classmethod
    async def _send_message_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_newsletters_window()

        await call.answer()

    @classmethod
    async def _send_message_message_handler(
        cls,
        message: Message,
        an_manager: ANManager,
    ) -> None:
        message_data = message.model_dump()
        await an_manager.data_storage.set_data(message_data, "message_data")
        await an_manager.open_send_buttons_window()

        await an_manager.delete_message(message)

    @classmethod
    async def _send_buttons_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_send_message_window()
        if call.data == "skip":
            message_data = await an_manager.data_storage.get_data("message_data")
            message_data["reply_markup"] = None
            message_data = Message(**message_data).model_dump()

            await an_manager.data_storage.set_data(message_data, "message_data")
            await an_manager.open_message_preview_window()

        await call.answer()

    @classmethod
    async def _send_buttons_message_handler(
        cls,
        message: Message,
        an_manager: ANManager,
    ) -> None:
        try:
            message_data = await an_manager.data_storage.get_data("message_data")
            message_data["reply_markup"] = an_manager.inline_keyboard.build_buttons(
                message.text
            )
            message_data = Message(**message_data).model_dump()

            await an_manager.data_storage.set_data(message_data, "message_data")
            await an_manager.open_message_preview_window()

        except (Exception,):
            text = an_manager.i18n.gettext("nl-send-buttons-error")
            await an_manager.open_send_buttons_window(text)

        await an_manager.delete_message(message)

    @classmethod
    async def _message_preview_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_send_buttons_window()
        elif call.data == "next":
            await an_manager.open_choose_options_window()

        await call.answer()

    @classmethod
    async def _choose_options_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_message_preview_window()
        elif call.data == "later":
            await an_manager.open_send_datetime_window()
        elif call.data == "now":
            await an_manager.open_confirmation_now_window()

        await call.answer()

    @classmethod
    async def _confirmation_now_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_choose_options_window()
        elif call.data == "confirm":
            message_data = await an_manager.data_storage.get_data("message_data")
            admin_user_id = an_manager.user.id

            asyncio.create_task(
                run_broadcast(message_data=message_data, admin_user_id=admin_user_id)
            )
            await an_manager.open_newsletters_window()

        await call.answer()

    @classmethod
    async def _send_datetime_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_choose_options_window()

        await call.answer()

    @classmethod
    async def _send_datetime_message_handler(
        cls,
        message: Message,
        an_manager: ANManager,
    ) -> None:
        if message.content_type == "text":
            datetime_obj = validate_datetime(message.text)

            if datetime_obj is None:
                text = an_manager.i18n.gettext("nl-send-datetime-error")
                await an_manager.open_send_datetime_window(text)
            else:
                await an_manager.data_storage.set_data(datetime_obj, "datetime_obj")
                await an_manager.open_confirmation_later_window()

        await an_manager.delete_message(message)

    @classmethod
    async def _confirmation_later_callback_handler(
        cls,
        call: CallbackQuery,
        an_manager: ANManager,
    ) -> None:
        if call.data == "back":
            await an_manager.open_send_datetime_window()
        elif call.data == "confirm":
            message_data = await an_manager.data_storage.get_data("message_data")
            datetime_obj = await an_manager.data_storage.get_data("datetime_obj")
            admin_user_id = an_manager.user.id

            an_manager.apscheduler.add_job(
                func=run_broadcast,
                trigger=DateTrigger(datetime_obj),
                kwargs={
                    "message_data": message_data,
                    "admin_user_id": admin_user_id,
                },
                id=f"broadcast_{uuid.uuid4().hex[:12]}",
                jobstore=BROADCAST_JOBSTORE,
                replace_existing=True,
            )

            await an_manager.open_newsletters_window()

        await call.answer()

    @classmethod
    async def _default_message_handler(
        cls,
        message: Message,
        an_manager: ANManager,
    ) -> None:
        await an_manager.delete_message(message)

    def register(self, dp: Dispatcher):
        router = Router()

        router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
        router.message.filter(F.chat.type == ChatType.PRIVATE)

        router.callback_query.register(
            self._newsletters_callback_handler,
            ANState.newsletters,
        )
        router.message.register(
            self._default_message_handler,
            ANState.newsletters,
        )

        router.callback_query.register(
            self._newsletter_callback_handler,
            ANState.newsletter,
        )
        router.message.register(
            self._default_message_handler,
            ANState.newsletter,
        )

        router.callback_query.register(
            self._newsletter_delete_callback_handler,
            ANState.newsletter_delete,
        )
        router.message.register(
            self._default_message_handler,
            ANState.newsletter_delete,
        )

        router.callback_query.register(
            self._send_message_callback_handler,
            ANState.send_message,
        )
        router.message.register(
            self._send_message_message_handler,
            ANState.send_message,
        )

        router.callback_query.register(
            self._send_buttons_callback_handler,
            ANState.send_buttons,
        )
        router.message.register(
            self._send_buttons_message_handler,
            ANState.send_buttons,
        )

        router.callback_query.register(
            self._message_preview_callback_handler,
            ANState.message_preview,
        )
        router.message.register(
            self._default_message_handler,
            ANState.message_preview,
        )

        router.callback_query.register(
            self._choose_options_callback_handler,
            ANState.choose_options,
        )
        router.message.register(
            self._default_message_handler,
            ANState.choose_options,
        )

        router.callback_query.register(
            self._confirmation_now_callback_handler,
            ANState.confirmation_now,
        )
        router.message.register(
            self._default_message_handler,
            ANState.confirmation_now,
        )

        router.callback_query.register(
            self._send_datetime_callback_handler,
            ANState.send_datetime,
        )
        router.message.register(
            self._send_datetime_message_handler,
            ANState.send_datetime,
        )

        router.callback_query.register(
            self._confirmation_later_callback_handler,
            ANState.confirmation_later,
        )
        router.message.register(
            self._default_message_handler,
            ANState.confirmation_later,
        )

        dp.include_router(router)
