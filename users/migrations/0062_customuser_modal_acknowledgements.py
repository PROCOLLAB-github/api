from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0061_userlink_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="verification_notice_acknowledged_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Дата подтверждения уведомления о верификации",
            ),
        ),
        migrations.AddField(
            model_name="customuser",
            name="profile_fill_prompt_acknowledged_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Дата подтверждения напоминания о заполнении профиля",
            ),
        ),
    ]
