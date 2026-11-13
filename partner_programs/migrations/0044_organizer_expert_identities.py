from django.db import migrations


def create_organizer_expert_identities(apps, schema_editor):
    program = apps.get_model("partner_programs", "PartnerProgram")
    expert = apps.get_model("users", "Expert")
    db = schema_editor.connection.alias
    organizers = (
        program.managers.through.objects.using(db)
        .order_by("customuser_id")
        .values_list("customuser_id", flat=True)
        .distinct()
        .iterator(chunk_size=1000)
    )
    batch = []
    for user_id in organizers:
        batch.append(expert(user_id=user_id))
        if len(batch) == 1000:
            expert.objects.using(db).bulk_create(batch, ignore_conflicts=True)
            batch.clear()
    if batch:
        expert.objects.using(db).bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0043_project_copy_form"),
        ("users", "0066_alter_userachievement_files"),
    ]

    operations = [
        # Keep identities on rollback because manual assignments can reference them.
        migrations.RunPython(
            create_organizer_expert_identities, migrations.RunPython.noop
        ),
    ]
