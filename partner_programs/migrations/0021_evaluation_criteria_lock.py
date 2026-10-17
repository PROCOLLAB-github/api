from django.db import migrations, models
from django.utils import timezone


def freeze_existing(apps, schema_editor):
    scores = apps.get_model("project_rates", "ProjectScore")
    programs = apps.get_model("partner_programs", "PartnerProgram")
    ids = scores.objects.using(schema_editor.connection.alias).values_list(
        "criteria__partner_program_id", flat=True
    )
    programs.objects.using(schema_editor.connection.alias).filter(pk__in=ids).update(
        evaluation_criteria_locked_at=timezone.now()
    )


class Migration(migrations.Migration):
    dependencies = [
        ("partner_programs", "0020_partnerprogram_image_framing"),
        ("project_rates", "0003_projectexpertassignment"),
    ]
    operations = [
        migrations.AddField(
            model_name="partnerprogram",
            name="evaluation_criteria_locked_at",
            field=models.DateTimeField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name="partnerprogram",
            name="evaluation_criteria_version",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.RunPython(freeze_existing, migrations.RunPython.noop),
    ]
