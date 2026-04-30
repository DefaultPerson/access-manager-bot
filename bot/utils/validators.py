import re
from typing import Literal

# Telegram channel ID pattern: -100 + digits (e.g., -1002931287222)
CHANNEL_ID_PATTERN = re.compile(r"^-100\d{10,13}$")

# Telegram channel link patterns:
# - Public: https://t.me/username
# - Private/invite: https://t.me/+invitehash or https://t.me/joinchat/invitehash
CHANNEL_LINK_PATTERN = re.compile(
    r"^https://t\.me/(?:\+[\w-]+|joinchat/[\w-]+|[a-zA-Z][\w]{4,31})$"
)


def validate_channel_id(channel_id: str | int) -> tuple[bool, str | None]:
    """Validate Telegram channel ID format.

    Args:
        channel_id: Channel ID to validate (string or int)

    Returns:
        Tuple of (is_valid, error_message)

    Examples:
        >>> validate_channel_id("-1002931287222")
        (True, None)
        >>> validate_channel_id(-1002931287222)
        (True, None)
        >>> validate_channel_id("123456")
        (False, "Invalid channel ID format. Expected: -100XXXXXXXXXX")
    """
    channel_id_str = str(channel_id)

    if not CHANNEL_ID_PATTERN.match(channel_id_str):
        return False, "Invalid channel ID format. Expected: -100XXXXXXXXXX"

    return True, None


def validate_channel_link(link: str) -> tuple[bool, str | None]:
    """Validate Telegram channel link format.

    Args:
        link: Channel link to validate

    Returns:
        Tuple of (is_valid, error_message)

    Examples:
        >>> validate_channel_link("https://t.me/+Z0zOJpGxm101MTZi")
        (True, None)
        >>> validate_channel_link("https://t.me/EF9MERA")
        (True, None)
        >>> validate_channel_link("https://t.me/joinchat/AaBbCcDd")
        (True, None)
        >>> validate_channel_link("t.me/channel")
        (False, "Invalid link format. Expected: https://t.me/...")
    """
    if not link.startswith("https://t.me/"):
        return False, "Invalid link format. Expected: https://t.me/..."

    if not CHANNEL_LINK_PATTERN.match(link):
        return (
            False,
            "Invalid link format. Expected: https://t.me/username or https://t.me/+invitehash",
        )

    return True, None


def parse_channel_input(
    input_str: str,
) -> tuple[Literal["id", "link"] | None, str | int | None, str | None]:
    """Parse user input as either channel ID or link.

    Args:
        input_str: User input string

    Returns:
        Tuple of (input_type, parsed_value, error_message)
        - input_type: "id" or "link" or None if invalid
        - parsed_value: int for ID, str for link, None if invalid
        - error_message: Error description if invalid

    Examples:
        >>> parse_channel_input("-1002931287222")
        ("id", -1002931287222, None)
        >>> parse_channel_input("https://t.me/+Z0zOJpGxm101MTZi")
        ("link", "https://t.me/+Z0zOJpGxm101MTZi", None)
        >>> parse_channel_input("invalid")
        (None, None, "Invalid input. Expected channel ID (-100...) or link (https://t.me/...)")
    """
    input_str = input_str.strip()

    # Try to parse as channel ID
    if input_str.startswith("-"):
        is_valid, error = validate_channel_id(input_str)
        if is_valid:
            return "id", int(input_str), None
        # Continue to try as link

    # Try to parse as channel link
    if input_str.startswith("https://"):
        is_valid, error = validate_channel_link(input_str)
        if is_valid:
            return "link", input_str, None
        return None, None, error

    return (
        None,
        None,
        "Invalid input. Expected channel ID (-100...) or link (https://t.me/...)",
    )
