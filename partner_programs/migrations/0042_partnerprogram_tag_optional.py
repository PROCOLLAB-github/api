from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0041_registration_admin_russian"),
    ]

    operations = [
        migrations.AlterField(
            model_name="partnerprogram",
            name="tag",
            field=models.TextField(blank=True, verbose_name="Тег"),
        ),
    ]
