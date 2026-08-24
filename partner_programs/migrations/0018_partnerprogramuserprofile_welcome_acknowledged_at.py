from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0017_alter_partnerprogramproject_options"),
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
