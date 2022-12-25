from enum import Enum


class ChatType(Enum):
    DIRECT = "direct"
    PROJECT = "project"


class EventType(Enum):
    CHAT_MESSAGE = "chat_message"
    TYPING = "typing"
    READ = "read"
