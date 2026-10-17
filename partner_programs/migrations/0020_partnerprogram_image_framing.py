from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("partner_programs", "0019_legacy_project_team_policy")]

    operations = [
        migrations.AddField(
            model_name="partnerprogram",
            name="mobile_cover_image_address",
            field=models.URLField(
                blank=True, null=True, verbose_name="Ссылка на мобильную обложку"
            ),
        ),
        migrations.AddField(
            model_name="partnerprogram",
            name="image_framing",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="Кадрирование изображений программы"
            ),
        ),
    ]
