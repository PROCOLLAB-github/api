# Документация по вебсокетам чатов

## Общая инфа
URL для всего вебсокет-релейтед - `/ws/`

В данный момент есть только 1 Consumer (т.е. View, но для вебсокетов). Это ChatsConsumer, живет на `/ws/chats/`.

# ChatsConsumer
`/ws/chats/`

### Подключение
Чтобы законнектиться, укажите в хедерах авторизацию по Bearer токену (как и для всех других запросов в REST API).

### Events
Есть два типа ивентов, которые можно кидать - general events и chat-related events. Первые состоят только из user_online и user_offline, вторые содержат все остальное: новое сообщение, печатание, чтение и удаление (пока без редактирования)

Структура любого Event, который должен кидаться на вебсокет выглядит так:
```py
class Event:
    type: EventType
    content: dict
```
И соответственно EventType вот такой:
```py
# эти строки указывать в {"type": event_type}

class EventType(str, Enum):
    # CHATS RELATED EVENTS
    NEW_MESSAGE = "new_message"
    DELETE_MESSAGE = "delete_message"
    READ_MESSAGE = "message_read"
    TYPING = "user_typing"

    # GENERAL EVENTS
    SET_ONLINE = "set_online"
    SET_OFFLINE = "set_offline"
```
Пример того, как выглядит Event на новое сообщение
```json
{
  "type": "new_message",
  "content": {
    "chat_type": "direct",
    "chat_id": "12_23",
    "message": "hello world",
    "reply_to": 54
  }
}
```

## Методы e.g. Ивенты

### SET_ONLINE/SET_OFFLINE
Без параметров.

### NEW_MESSAGE
- `chat_type: str`\
`"direct"` или `"project"`, зависит от типа чата
- `chat_id: int/str`\
Если тип `"project"`, то тип будет `int` и это айди проекта, которому принадлежит чат. Если тип `"direct"`, то это `str`. Выглядит как `{user1_id}_{user2_id}`, **где первое число всегда меньше второго**.
- `message: str` текст сообщения
- `reply_to: Optional[int]` айди сообщения, на которое кидается ответ. Если его нет, то обязательно кидать `None`

### TYPING
- `chat_type` см выше
- `chat_id` см выше

### READ_MESSAGE
- `chat_type` см выше
- `chat_id` см выше
- `message_id: int` айди сообщение, которое прочитали

### DELETE_MESSAGE
- `chat_type` см выше
- `chat_id` см выше
- `message_id: int` айди сообщения, которое удаляем
