class ChatException(Exception):
    def get_error(self):
        return self.args[0]


class NonMatchingDirectChatIdException(ChatException):
    pass


class WrongChatIdException(ChatException):
    pass


class UserNotInChatException(ChatException):
    pass


class UserNotMessageAuthorException(ChatException):
    pass


class NonMatchingReplyChatIdException(ChatException):
    pass