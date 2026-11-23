import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("partner_programs", "0045_accelerator_program_format")]

    operations = [
        migrations.AddField(
            model_name="partnerprogram",
            name="landing_url",
            field=models.CharField(
                blank=True,
                help_text="Адрес сайта программы с http:// или https://.",
                max_length=200,
                validators=[
                    django.core.validators.URLValidator(
                        message="Укажите корректную ссылку с http:// или https://.",
                        schemes=["http", "https"],
                    )
                ],
                verbose_name="Ссылка «Подробнее»",
            ),
        )
    ]
