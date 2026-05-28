from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("moderation", "0003_program_moderation_rejection_reasons"),
    ]

    operations = [
        migrations.AlterField(
            model_name="moderationlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("submit_to_moderation", "Отправка на модерацию"),
                    ("submitted", "Отправка на модерацию"),
                    ("approve", "Одобрение"),
                    ("approved", "Одобрение"),
                    ("reject", "Отклонение"),
                    ("rejected", "Отклонение"),
                    ("withdraw", "Отзыв с модерации"),
                    ("withdrawn", "Отзыв с модерации"),
                    ("auto_freeze", "Автоматическая заморозка"),
                    ("freeze", "Ручная заморозка"),
                    ("restore", "Восстановление"),
                    ("archive", "Архивация"),
                    ("complete", "Завершение"),
                    ("verification_submitted", "Заявка на верификацию"),
                    ("verification_approve", "Верификация одобрена"),
                    ("verification_reject", "Верификация отклонена"),
                    ("verification_revoke", "Верификация отозвана"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="moderationlog",
            name="rejection_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("insufficient_data", "Недостаточно данных"),
                    ("platform_rules", "Нарушение правил платформы"),
                    ("duplicate", "Дублирующий чемпионат"),
                    ("inappropriate_content", "Некорректное содержание"),
                    ("suspicious_organizer", "Подозрительный организатор"),
                    ("other", "Другая причина"),
                ],
                max_length=40,
            ),
        ),
    ]
