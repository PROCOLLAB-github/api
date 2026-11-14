from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("partner_programs", "0044_organizer_expert_identities")]

    operations = [
        migrations.AlterField(
            model_name="partnerprogram",
            name="program_format",
            field=models.CharField(
                blank=True,
                choices=[
                    ("accelerator", "Акселератор"),
                    ("case_championship", "Кейс-чемпионат"),
                    ("hackathon", "Хакатон"),
                    ("noncompetitive", "Неконкурсная программа"),
                ],
                max_length=24,
                null=True,
                verbose_name="Формат программы",
            ),
        ),
    ]
