from django.db import migrations, models
import django.db.models.deletion


def remember_rendered_batch(apps, schema_editor):
    certificate = apps.get_model("partner_programs", "ProgramCertificate")
    certificate.objects.using(schema_editor.connection.alias).filter(
        pdf__isnull=False, rendered_batch__isnull=True
    ).update(rendered_batch_id=models.F("batch_id"))


class Migration(migrations.Migration):
    dependencies = [("partner_programs", "0030_program_solution_foundation")]

    operations = [
        migrations.AddField(
            model_name="programcertificate",
            name="rendered_batch",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="rendered_certificates",
                to="partner_programs.programcertificatebatch",
            ),
        ),
        migrations.RunPython(remember_rendered_batch, migrations.RunPython.noop),
    ]
