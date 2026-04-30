from dataclasses import dataclass
from typing import Optional

from aiogram.utils.i18n.core import I18n
from aiogram.utils.keyboard import InlineKeyboardBuilder as Builder
from aiogram.utils.keyboard import InlineKeyboardButton as Button
from aiogram.utils.keyboard import InlineKeyboardMarkup as Markup

from bot.utils.misc import validate_url


@dataclass
class InlineKeyboard:
    """Newsletter inline keyboard builder with i18n support."""

    def __init__(self, i18n: I18n, language_code: str = "en") -> None:
        """Initialize inline keyboard.

        Args:
            i18n: I18n instance for translations
            language_code: Language code
        """
        self.i18n = i18n
        self.language_code = language_code

    def _get_button(self, code: str, url: str = None) -> Button:
        """Get button with translated text.

        Args:
            code: Button code (add, delete, etc.)
            url: Optional URL for link button

        Returns:
            InlineKeyboardButton
        """
        text = self.i18n.gettext(f"nl-btn-{code}", locale=self.language_code)
        if not url:
            return Button(text=text, callback_data=code)
        return Button(text=text, url=url)

    def back(self) -> Markup:
        """Back button."""
        return Markup(inline_keyboard=[[self._get_button("back")]])

    def back_add(self) -> Markup:
        """Back and Add buttons."""
        return Markup(
            inline_keyboard=[
                [self._get_button("back"), self._get_button("add")],
            ]
        )

    def back_next(self) -> Markup:
        """Back and Next buttons."""
        return Markup(
            inline_keyboard=[
                [self._get_button("back"), self._get_button("next")],
            ]
        )

    def back_delete(self) -> Markup:
        """Back and Delete buttons."""
        return Markup(
            inline_keyboard=[
                [self._get_button("back"), self._get_button("delete")],
            ]
        )

    def back_confirm(self) -> Markup:
        """Back and Confirm buttons."""
        return Markup(
            inline_keyboard=[
                [self._get_button("back"), self._get_button("confirm")],
            ]
        )

    def newsletters(
        self, items: list[tuple[str, str]], page: int, total_pages: int
    ) -> Markup:
        """Newsletter list with pagination."""
        paginator = InlineKeyboardPaginator(
            items=items,
            current_page=page,
            total_pages=total_pages,
            after_reply_markup=self.back_add(),
        )
        return paginator.as_markup()

    def send_message(self) -> Markup:
        """Send message window - back button only."""
        return Markup(inline_keyboard=[[self._get_button("back")]])

    def send_buttons(self) -> Markup:
        """Send buttons window - back and skip."""
        return Markup(
            inline_keyboard=[
                [self._get_button("back"), self._get_button("skip")],
            ]
        )

    def message_preview(self) -> Markup:
        """Message preview - back and next."""
        return Markup(
            inline_keyboard=[
                [self._get_button("back"), self._get_button("next")],
            ]
        )

    def choose_options(self) -> Markup:
        """Choose send time - later/now and back."""
        return Markup(
            inline_keyboard=[
                [self._get_button("later"), self._get_button("now")],
                [self._get_button("back")],
            ]
        )

    @staticmethod
    def build_buttons(buttons: str) -> Optional[Markup]:
        """Build inline keyboard from text.

        Format:
            Text | URL
            Text1 | URL1, Text2 | URL2  # multiple in row
            Text1 | URL1
            Text2 | URL2                # in column

        Args:
            buttons: Button text in format "Text | URL"

        Returns:
            InlineKeyboardMarkup or None
        """
        if not buttons:
            return None

        rows = [row.split(",") for row in buttons.split("\n")]

        return Markup(
            inline_keyboard=[
                [
                    Button(
                        text=b.split("|")[0].strip(),
                        url=validate_url(b.split("|")[1].strip()),
                    )
                    for b in row
                ]
                for row in rows
            ]
        )


class InlineKeyboardPaginator:
    """Smart pagination for inline keyboards."""

    first_page_label = "« {}"
    previous_page_label = "‹ {}"
    current_page_label = "· {} ·"
    next_page_label = "{} ›"
    last_page_label = "{} »"

    def __init__(
        self,
        items: list[tuple[str, str]],
        current_page: int = 1,
        total_pages: int = 1,
        row_width: int = 1,
        data_pattern: str = "page:{}",
        before_reply_markup: Optional[Markup] = None,
        after_reply_markup: Optional[Markup] = None,
    ) -> None:
        """Initialize paginator.

        Args:
            items: List of (text, callback_data) tuples
            current_page: Current page number
            total_pages: Total pages count
            row_width: Buttons per row for items
            data_pattern: Pattern for page callback data
            before_reply_markup: Markup to add before items
            after_reply_markup: Markup to add after pagination
        """
        self.items = items
        self.current_page = current_page
        self.total_pages = total_pages
        self.row_width = row_width
        self.data_pattern = data_pattern

        self.builder = Builder()
        self.before_reply_markup = before_reply_markup
        self.after_reply_markup = after_reply_markup

    def _items_builder(self) -> Builder:
        """Build items section."""
        builder = Builder()

        for key, val in self.items:
            builder.button(text=key, callback_data=val)
        builder.adjust(self.row_width)

        return builder

    def _navigation_builder(self) -> Builder:
        """Build navigation section."""
        builder = Builder()
        keyboard_dict = {}

        if self.total_pages > 1:
            if self.total_pages <= 5:
                for page in range(1, self.total_pages + 1):
                    keyboard_dict[page] = page
            else:
                if self.current_page <= 3:
                    page_range = range(1, 4)
                    keyboard_dict[4] = self.next_page_label.format(4)
                    keyboard_dict[self.total_pages] = self.last_page_label.format(
                        self.total_pages
                    )
                elif self.current_page > self.total_pages - 3:
                    keyboard_dict[1] = self.first_page_label.format(1)
                    keyboard_dict[self.total_pages - 3] = (
                        self.previous_page_label.format(self.total_pages - 3)
                    )
                    page_range = range(self.total_pages - 2, self.total_pages + 1)
                else:
                    keyboard_dict[1] = self.first_page_label.format(1)
                    keyboard_dict[self.current_page - 1] = (
                        self.previous_page_label.format(self.current_page - 1)
                    )
                    keyboard_dict[self.current_page + 1] = self.next_page_label.format(
                        self.current_page + 1
                    )
                    keyboard_dict[self.total_pages] = self.last_page_label.format(
                        self.total_pages
                    )
                    page_range = [self.current_page]
                for page in page_range:
                    keyboard_dict[page] = page
            keyboard_dict[self.current_page] = self.current_page_label.format(
                self.current_page
            )

            for key, val in sorted(keyboard_dict.items()):
                builder.button(
                    text=str(val), callback_data=str(self.data_pattern.format(key))
                )
            builder.adjust(5)

        return builder

    def as_markup(self) -> Markup:
        """Build final markup with all sections."""
        if self.before_reply_markup:
            self.builder.attach(
                Builder(markup=self.before_reply_markup.inline_keyboard)
            )

        self.builder.attach(self._items_builder())
        self.builder.attach(self._navigation_builder())

        if self.after_reply_markup:
            self.builder.attach(Builder(markup=self.after_reply_markup.inline_keyboard))

        return self.builder.as_markup()
