from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("project_rates", "0006_expertjoinednotification_and_more")]

    operations = [
        migrations.AddField(
            model_name="expertinvitation",
            name="all_cases",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="expertinvitation",
            name="case_names",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
