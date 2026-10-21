from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vacancy", "0010_vacancy_city")]

    operations = [
        migrations.AddField(
            model_name="vacancy",
            name="resume_on_publish",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text="Временно скрыта вместе с черновиком проекта, а не перенесена в архив.",
            ),
        ),
    ]
