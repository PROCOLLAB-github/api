from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("partner_programs", "0030_program_solution_foundation")]

    operations = [
        migrations.AddField(
            model_name="partnerprogramfield",
            name="solution_options",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
