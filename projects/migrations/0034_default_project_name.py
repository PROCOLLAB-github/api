from django.db import migrations, models

# Match Python str.strip() whitespace independently of database collation.
BLANK_NAME_PATTERN = (
    "^[\t\n\v\f\r\x1c-\x1f \x85\u00a0\u1680"
    "\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$"
)


def fill_unnamed_projects(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Project.objects.using(schema_editor.connection.alias).filter(
        models.Q(name__isnull=True) | models.Q(name__regex=BLANK_NAME_PATTERN)
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
