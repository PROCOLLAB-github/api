from django.db import migrations, models


def fill_unnamed_projects(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Project.objects.using(schema_editor.connection.alias).filter(
        models.Q(name__isnull=True) | models.Q(name__regex=r"^\s*$")
    ).update(name="Проект без названия")


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0033_delete_projectnews"),
    ]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="name",
            field=models.CharField(
                blank=True, default="Проект без названия", max_length=256, null=True
            ),
        ),
        # Preserve assigned names on rollback; they may have been chosen by a user.
        migrations.RunPython(fill_unnamed_projects, migrations.RunPython.noop),
    ]
