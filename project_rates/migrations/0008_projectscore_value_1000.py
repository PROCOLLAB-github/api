from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("project_rates", "0007_expertinvitation_case_scope")]

    operations = [
        migrations.AlterField(
            model_name="projectscore",
            name="value",
            field=models.CharField(
                verbose_name="Значение", blank=True, max_length=1000, null=True
            ),
        ),
    ]
