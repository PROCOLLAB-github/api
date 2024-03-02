# Generated by Django 4.2.3 on 2024-02-01 09:34
from django.contrib.contenttypes.models import ContentType
from django.db import migrations
from core.models import Skill, SkillToObject
from users.models import CustomUser


custom_user_content_type = ContentType.objects.get_for_model(CustomUser)


def migrate_key_skills_to_skills(apps, schema_editor):
    for user in CustomUser.objects.all():
        if user.key_skills:
            for skill_name in user.key_skills.lower().split(','):
                skill_name = skill_name.strip()
                skill = Skill.objects.filter(name__iexact=skill_name).first()
                if skill:
                    SkillToObject.objects.get_or_create(
                        skill=skill, content_type=custom_user_content_type, object_id=user.id
                    )


def reverse(apps, schema_editor):
    SkillToObject.objects.filter(content_type=custom_user_content_type).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_add_skills_from_dataset"),
        ("users", "0044_auto_20240128_2236")
    ]

    operations = [
        migrations.RunPython(migrate_key_skills_to_skills, reverse_code=reverse),
    ]
