from dataclasses import dataclass
from enum import Enum


class ChatType(str, Enum):
    DIRECT = "direct"
    PROJECT = "project"


class EventType(str, Enum):
    # CHATS RELATED EVENTS
    NEW_MESSAGE = "new_message"
    DELETE_MESSAGE = "delete_message"
    READ_MESSAGE = "message_read"
    TYPING = "user_typing"
    EDIT_MESSAGE = "edit_message"

    # GENERAL EVENTS
    SET_ONLINE = "set_online"
    SET_OFFLINE = "set_offline"


class EventGroupType(str, Enum):
    CHATS_RELATED = "CHATS_RELATED"
    GENERAL_EVENTS = "GENERAL_EVENTS"


@dataclass(frozen=True)
class Event:
    type: EventType  # noqa: A003, VNE003
    content: dict
