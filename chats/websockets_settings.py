from enum import Enum


class ChatType(Enum):
    DIRECT = "direct"
    PROJECT = "project"


class EventType(Enum):
    CHAT_MESSAGE = "chat_message"
    TYPING = "typing"
    READ = "read"
    LAST_30_MESSAGES = "last_30_messages"
