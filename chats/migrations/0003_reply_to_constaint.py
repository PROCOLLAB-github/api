# Generated by Django 4.1.3 on 2023-02-08 12:55

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chats", "0002_directchatmessage_is_deleted_and_more"),
    ]

    operations = [
        # migrations.RunSQL(
        #     sql="""
        #     ALTER TABLE chats_directchatmessage
        #     ADD CONSTRAINT my_constraint
        #     CHECK (
        #       (chats_directchatmessage.reply_to_id IS NULL) OR
        #       (chats_directchatmessage.chat_id = (SELECT chats_directchatmessage.chat_id FROM chats_directchatmessage WHERE chats_directchatmessage.id = chats_directchatmessage.reply_to_id))
        #     )
        #     """,
        #     reverse_sql="""
        #         ALTER TABLE chats_directchatmessage
        #         DROP CONSTRAINT my_constraint
        #     """)
    ]

