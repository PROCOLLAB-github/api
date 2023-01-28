class ChatException(Exception):
    pass


class NonMatchingDirectChatIdException(ChatException):
    pass


class WrongChatIdException(ChatException):
    pass
