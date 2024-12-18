# Generated by Django 4.2.11 on 2024-12-02 17:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vacancy", "0006_vacancy_datetime_closed"),
    ]

    operations = [
        migrations.AddField(
            model_name="vacancy",
            name="required_experience",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Без опыта", "Без опыта"),
                    ("До 1 года", "До 1 года"),
                    ("От 1 года до 3 лет", "От 1 года до 3 лет"),
                    ("От 3 лет и более", "От 3 лет и более"),
                ],
                max_length=50,
                null=True,
                verbose_name="Требуемый опыт",
            ),
        ),
        migrations.AddField(
            model_name="vacancy",
            name="work_format",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Удаленная работа", "Удаленная работа"),
                    ("Работа в офисе", "Работа в офисе"),
                    ("Смешанная", "Смешанная"),
                ],
                max_length=50,
                null=True,
                verbose_name="Формат работы",
            ),
        ),
        migrations.AddField(
            model_name="vacancy",
            name="work_schedule",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Полный рабочий день", "Полный рабочий день"),
                    ("Сменный график", "Сменный график"),
                    ("Гибкий график", "Гибкий график"),
                    ("Частичная занятость", "Частичная занятость"),
                    ("Стажировка", "Стажировка"),
                ],
                max_length=50,
                null=True,
                verbose_name="График работы",
            ),
        ),
    ]
