from channels.testing import WebsocketCommunicator
from django.test import TestCase
from chats.consumers import ChatConsumer
from django.contrib.auth import get_user_model
from chats.tests.constants import TEST_USER1, TEST_USER2, TEST_USER3
from asgiref.sync import sync_to_async
from chats.models import DirectChatMessage


class DirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create(**TEST_USER1)
        cls.user = user

    async def test_connect_with_crutch(self):
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

    async def test_send_new_message_direct_with_myself(
        self,
    ):  # Сообщения в чат с самим собой
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_1",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        self.assertFalse("error" in response.keys())
        content = response["content"]
        message = content["message"]
        # Проверка input == output
        self.assertEqual(response["type"], data["type"])
        self.assertEqual(data["content"]["chat_id"], content["chat_id"])
        self.assertEqual(data["content"]["text"], message["text"])
        self.assertEqual(data["content"]["reply_to"], message["reply_to"])
        self.assertEqual(data["content"]["is_edited"], message["is_edited"])
        self.assertFalse(message["is_deleted"])

    async def test_send_new_message_to_orher_chat(self):  # Сообщение в чужой чат
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER3)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        self.assertTrue("error" in response.keys())

    async def test_is_edited_new_message_direct_with_myself(
        self,
    ):  # Проверка на редактированность нового сообщения
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_1",
                "text": "hello world",
                "reply_to": None,
                "is_edited": True,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message = response["content"]["message"]
        self.assertTrue(message["is_edited"] != data["content"]["is_edited"])

    async def test_new_message_with_two_users(self):  # Чат на двоих новое сообщение
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        self.assertFalse("error" in response.keys())

    async def test_read_message_with_new_user(
        self,
    ):  # Чтение чужих сообщений в своём чате
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message = response["content"]["message"]
        message_id = message["id"]
        await communicator.disconnect()
        # Read message with new user
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "message_read",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertFalse("error" in response.keys())
        self.assertTrue(direct_message.is_read)

    async def test_read_message_with_myself(self):  # Чтение своих сообщений
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message = response["content"]["message"]
        message_id = message["id"]
        data = {
            "type": "message_read",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        self.assertTrue("error" in response.keys())
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertFalse(direct_message.is_read)

    async def test_read_someone_elses_message(
        self,
    ):  # Чтение чужих сообщение в чужом чате
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER3)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message = response["content"]["message"]
        message_id = message["id"]
        await communicator.disconnect()
        # Read message with new user
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "message_read",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue("error" in response.keys())
        self.assertFalse(direct_message.is_read)

    async def test_edit_my_message_in_myself(self):  # Редактирование в чате с самим собой
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_1",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        text = "edited text"
        data = {
            "type": "edit_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_1",
                "message_id": message_id,
                "text": text,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue(direct_message.is_edited)
        self.assertEqual(direct_message.text, text)

    async def test_edit_my_message(self):  # Редактирование в чате с кем-то
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        text = "edited text"
        data = {
            "type": "edit_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
                "text": text,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue(direct_message.is_edited)
        self.assertEqual(direct_message.text, text)

    async def test_edit_other_message(
        self,
    ):  # Редактирование чужих сообщений в своём чате
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        await communicator.disconnect()
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        text = "edited text"
        data = {
            "type": "edit_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
                "text": text,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue("error" in response.keys())
        self.assertFalse(direct_message.is_edited)
        self.assertTrue(direct_message.text != text)

    async def test_edit_other_message_in_other_char(
        self,
    ):  # Редактирование чужих сообщений в чужом чате
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER3)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        await communicator.disconnect()

        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        text = "edited text"
        data = {
            "type": "edit_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
                "text": text,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue("error" in response.keys())
        self.assertFalse(direct_message.is_edited)
        self.assertTrue(direct_message.text != text)

    async def test_delete_message_in_myself(
        self,
    ):  # Удаление сообщений в чате с самим собой
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_1",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        data = {
            "type": "delete_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_1",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue(direct_message.is_deleted)

    async def test_delete_message(self):  # Удаление сообщений в чате с кем-то
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        data = {
            "type": "delete_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertTrue(direct_message.is_deleted)

    async def test_delete_other_message(self):  # Удаление чужих сообщений в чате с кем-то
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        await communicator.disconnect()

        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "delete_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertFalse(direct_message.is_deleted)

    async def test_delete_other_message_in_other_chat(
        self,
    ):  # Удаление чужих сообщений в чужом чате
        await sync_to_async(get_user_model().objects.create)(**TEST_USER2)
        user = await sync_to_async(get_user_model().objects.create)(**TEST_USER3)
        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = self.user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "new_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "text": "hello world",
                "reply_to": None,
                "is_edited": False,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        message_id = response["content"]["message"]["id"]
        await communicator.disconnect()

        communicator = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        communicator.scope["user"] = user
        connected, subprotocol = await communicator.connect()
        data = {
            "type": "delete_message",
            "content": {
                "chat_type": "direct",
                "chat_id": "1_2",
                "message_id": message_id,
            },
        }
        await communicator.send_json_to(data)
        response = await communicator.receive_json_from()
        direct_message = await sync_to_async(DirectChatMessage.objects.get)(id=1)
        self.assertFalse(direct_message.is_deleted)
