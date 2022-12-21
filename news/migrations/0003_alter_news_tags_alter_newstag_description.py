# Generated by Django 4.1.2 on 2022-10-29 12:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0002_newstag_news_tags"),
    ]

    operations = [
        migrations.AlterField(
            model_name="news",
            name="tags",
            field=models.ManyToManyField(
                blank=True, null=True, to="news.newstag", verbose_name="Список тегов"
            ),
        ),
        migrations.AlterField(
            model_name="newstag",
            name="description",
            field=models.CharField(
                blank=True, max_length=512, null=True, verbose_name="Описание тега"
            ),
        ),
    ]
