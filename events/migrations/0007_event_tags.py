# Generated by Django 4.1.3 on 2023-03-23 15:41

from django.db import migrations
import taggit.managers


class Migration(migrations.Migration):

    dependencies = [
        ("taggit", "0005_auto_20220424_2025"),
        ("events", "0006_event_event_type_event_favorites_event_likes_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="tags",
            field=taggit.managers.TaggableManager(
                help_text="A comma-separated list of tags.",
                through="taggit.TaggedItem",
                to="taggit.Tag",
                verbose_name="Tags",
            ),
        ),
    ]
