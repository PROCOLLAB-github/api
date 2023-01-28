from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ChatType(str, Enum):
    DIRECT = "direct"
    PROJECT = "project"


class EventType(str, Enum):
    NEW_MESSAGE = "new_message"
    TYPING = "typing"
    READ_MESSAGE = "read"
    DELETE_MESSAGE = "delete_message"
    SET_ONLINE = "set_online"
    SET_OFFLINE = "set_offline"


class EventGroupType(str, Enum):
    CHATS_RELATED = "CHATS_RELATED"
    GENERAL_EVENTS = "GENERAL_EVENTS"


@dataclass(slots=True, frozen=True)
class Content:
    chat_id: Optional[str]
    message: Optional[str]


@dataclass(slots=True, frozen=True)
class Event:
    type: EventType
    content: Optional[Content]
