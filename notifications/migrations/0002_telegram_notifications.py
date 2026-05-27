from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationdelivery",
            name="attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="notificationdelivery",
            name="last_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="notificationdelivery",
            name="provider_message_id",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name="notificationdelivery",
            name="channel",
            field=models.CharField(
                choices=[
                    ("in_app", "In-app"),
                    ("email", "Email"),
                    ("telegram", "Telegram"),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="TelegramAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "telegram_chat_id",
                    models.BigIntegerField(blank=True, db_index=True, null=True),
                ),
                ("telegram_username", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(db_index=True, default=False)),
                ("linked_at", models.DateTimeField(blank=True, null=True)),
                ("datetime_created", models.DateTimeField(auto_now_add=True)),
                ("datetime_updated", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telegram_account",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Telegram account",
                "verbose_name_plural": "Telegram accounts",
            },
        ),
        migrations.CreateModel(
            name="TelegramLinkToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telegram_link_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Telegram link token",
                "verbose_name_plural": "Telegram link tokens",
            },
        ),
        migrations.CreateModel(
            name="NotificationChannelPreference",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("telegram", "Telegram")],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            (
                                "program_submitted_to_moderation",
                                "Program submitted to moderation",
                            ),
                            (
                                "program_moderation_approved",
                                "Program moderation approved",
                            ),
                            (
                                "program_moderation_rejected",
                                "Program moderation rejected",
                            ),
                            (
                                "company_verification_submitted",
                                "Company verification submitted",
                            ),
                            (
                                "company_verification_approved",
                                "Company verification approved",
                            ),
                            (
                                "company_verification_rejected",
                                "Company verification rejected",
                            ),
                            ("expert_projects_assigned", "Expert projects assigned"),
                        ],
                        db_index=True,
                        max_length=64,
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("datetime_created", models.DateTimeField(auto_now_add=True)),
                ("datetime_updated", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_channel_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Notification channel preference",
                "verbose_name_plural": "Notification channel preferences",
            },
        ),
        migrations.AddIndex(
            model_name="telegramlinktoken",
            index=models.Index(
                fields=["user", "used_at", "expires_at"],
                name="notificatio_user_id_bea324_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationchannelpreference",
            constraint=models.UniqueConstraint(
                fields=("user", "channel", "event_type"),
                name="unique_notification_channel_preference",
            ),
        ),
        migrations.AddIndex(
            model_name="notificationchannelpreference",
            index=models.Index(
                fields=["user", "channel", "enabled"],
                name="notificatio_user_id_e9a3b6_idx",
            ),
        ),
    ]
