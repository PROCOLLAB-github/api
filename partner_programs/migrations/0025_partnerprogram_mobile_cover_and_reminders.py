from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0024_organizer_legal_settings_contact_export"),
    ]

    operations = [
        migrations.AddField(
            model_name="partnerprogram",
            name="mobile_cover_image_address",
            field=models.URLField(
                blank=True,
                help_text=(
                    "Optional mobile-optimized cover image. Falls back to "
                    "cover_image_address when empty."
                ),
                null=True,
                verbose_name="Mobile cover image URL",
            ),
        ),
        migrations.AddField(
            model_name="partnerprogram",
            name="sent_reminders",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="Sent readiness reminders",
            ),
        ),
    ]
