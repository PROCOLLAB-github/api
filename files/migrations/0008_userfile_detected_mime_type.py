from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("files", "0007_auto_20230929_1727")]

    operations = [
        migrations.AddField(
            model_name="userfile",
            name="detected_mime_type",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
    ]
