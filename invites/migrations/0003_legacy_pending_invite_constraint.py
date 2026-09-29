from django.db import migrations, models


def require_no_duplicate_pending(apps, schema_editor):
    Invite = apps.get_model("invites", "Invite")
    duplicates = list(
        Invite.objects.using(schema_editor.connection.alias)
        .filter(is_accepted__isnull=True)
        .values("project_id", "user_id")
        .annotate(count=models.Count("pk"))
        .filter(count__gt=1)
        .order_by("project_id", "user_id")[:20]
    )
    if duplicates:
        raise RuntimeError(
            "Duplicate pending invites: migration stopped without choosing a winner. "
            "Run the read-only query in docs/invite-integrity-api.md and resolve "
            f"conflicts separately. First groups: {duplicates}"
        )


class Migration(migrations.Migration):
    dependencies = [("invites", "0002_invite_specialization")]
    operations = [
        migrations.RunPython(require_no_duplicate_pending, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="invite",
            constraint=models.UniqueConstraint(
                fields=("project", "user"),
                condition=models.Q(is_accepted__isnull=True),
                name="uniq_legacy_pending_invite",
            ),
        ),
    ]
