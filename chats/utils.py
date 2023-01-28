def clean_message_text(text: str) -> str:
    """
    Cleans message text.
    """

    return text.strip()


def validate_message_text(text: str) -> bool:
    """
    Validates message text.
    """
    # TODO: add bad word filter
    return 0 < len(text) <= 8192


def get_user_channel_cache_key(user) -> str:
    return f"user_channel_{user.pk}"
