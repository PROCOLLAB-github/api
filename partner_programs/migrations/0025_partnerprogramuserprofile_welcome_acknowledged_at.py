from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0024_evaluation_amended_at_evaluationamendment"),
    ]

    operations = [
        migrations.AddField(
            model_name="partnerprogramuserprofile",
            name="welcome_acknowledged_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Дата подтверждения приветствия программы",
            ),
        ),
    ]
