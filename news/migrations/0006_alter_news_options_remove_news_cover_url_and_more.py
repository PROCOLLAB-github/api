# Generated by Django 4.2.3 on 2023-07-18 23:25

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0005_alter_userfile_options"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("news", "0005_news_content_type_news_object_id"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="news",
            options={
                "ordering": ["-datetime_created"],
                "verbose_name": "Новость",
                "verbose_name_plural": "Новости",
            },
        ),
        migrations.RemoveField(
            model_name="news",
            name="cover_url",
        ),
        migrations.RemoveField(
            model_name="news",
            name="short_text",
        ),
        migrations.RemoveField(
            model_name="news",
            name="tags",
        ),
        migrations.RemoveField(
            model_name="news",
            name="title",
        ),
        migrations.AddField(
            model_name="news",
            name="files",
            field=models.ManyToManyField(
                blank=True, related_name="news", to="files.userfile"
            ),
        ),
        migrations.AlterField(
            model_name="news",
            name="content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="news",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AlterField(
            model_name="news",
            name="object_id",
            field=models.PositiveIntegerField(),
        ),
        migrations.DeleteModel(
            name="NewsTag",
        ),
    ]
