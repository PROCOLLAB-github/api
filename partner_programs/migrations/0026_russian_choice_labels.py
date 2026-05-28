from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0025_partnerprogram_mobile_cover_and_reminders"),
    ]

    operations = [
        migrations.AlterField(
            model_name="legaldocument",
            name="type",
            field=models.CharField(
                choices=[
                    ("privacy_policy", "Политика обработки персональных данных"),
                    ("participant_consent", "Согласие участника на обработку данных"),
                    ("participation_terms", "Правила участия платформы"),
                    ("organizer_terms", "Условия для организатора"),
                ],
                db_index=True,
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="partnerprogram",
            name="participation_format",
            field=models.CharField(
                choices=[
                    ("individual", "Индивидуально"),
                    ("team", "Командно"),
                ],
                default="team",
                help_text="Team-size rule for a project linked to this championship.",
                max_length=20,
                verbose_name="Participation format",
            ),
        ),
        migrations.AlterField(
            model_name="partnerprogram",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Черновик"),
                    ("pending_moderation", "На модерации"),
                    ("published", "Опубликован"),
                    ("rejected", "На доработке"),
                    ("completed", "Завершен"),
                    ("frozen", "Заморожен"),
                    ("archived", "Архив"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
                verbose_name="Program status",
            ),
        ),
        migrations.AlterField(
            model_name="partnerprogram",
            name="verification_status",
            field=models.CharField(
                choices=[
                    ("not_requested", "Не запрошена"),
                    ("pending", "На рассмотрении"),
                    ("verified", "Подтверждена"),
                    ("rejected", "Отклонена"),
                    ("revoked", "Отозвана"),
                ],
                db_index=True,
                default="not_requested",
                max_length=20,
                verbose_name="Verification status",
            ),
        ),
        migrations.AlterField(
            model_name="partnerprogramverificationrequest",
            name="rejection_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("company_not_confirmed", "Данные компании не подтверждены"),
                    ("insufficient_documents", "Недостаточно документов"),
                    ("invalid_documents", "Некорректные документы"),
                    ("contact_not_verified", "Контактное лицо не подтверждено"),
                    ("other", "Другая причина"),
                ],
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="partnerprogramverificationrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "На рассмотрении"),
                    ("approved", "Одобрена"),
                    ("rejected", "Отклонена"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
    ]
