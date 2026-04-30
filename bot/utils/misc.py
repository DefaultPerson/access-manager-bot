import pickle
import re
from datetime import datetime
from typing import Any, Union

from aiogram.fsm.context import FSMContext


def validate_url(url: str) -> Union[str, None]:
    url_pattern = re.compile(r'https?://\S+|www\.\S+')
    matches = re.findall(url_pattern, url)

    return matches[0] if matches else None


def validate_datetime(datetime_string: str) -> Union[datetime, None]:
    try:
        datetime_obj = datetime.strptime(datetime_string, "%Y-%m-%d %H:%M")
    except ValueError:
        return None

    return datetime_obj


class DataStorage:
    def __init__(self, state: FSMContext) -> None:
        self.state = state

    @classmethod
    def data_to_hex(cls, data: Any) -> str:
        return pickle.dumps(data).hex()

    @classmethod
    def hext_to_data(cls, hext: str) -> Any:
        return pickle.loads(bytes.fromhex(hext))

    async def set_data(self, data: Any, key: str) -> None:
        data = {key: self.data_to_hex(data)}
        await self.state.update_data(**data)

    async def get_data(self, key: str) -> Any:
        state_data = await self.state.get_data()
        return self.hext_to_data(state_data.get(key))
