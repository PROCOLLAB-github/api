from django.conf import settings
from django.db import migrations


def add_default_images(apps, schema_editor):
    base = settings.PROJECT_DEFAULT_PACK_URL.rstrip("/")
    if not base:
        return
    files = apps.get_model("files", "UserFile")
    for model, directory, prefix in (
        ("DefaultProjectAvatar", "avatars", "avatar"),
        ("DefaultProjectCover", "covers", "cover"),
    ):
        catalog = apps.get_model("projects", model)
        for index in range(1, 13):
            name = f"{prefix}-{index:02d}"
            url = f"{base}/{directory}/{name}.jpg"
            files.objects.get_or_create(
                link=url,
                defaults={"name": name, "extension": "jpg", "mime_type": "image/jpeg"},
            )
            catalog.objects.get_or_create(image_id=url)


class Migration(migrations.Migration):
    dependencies = [("projects", "0035_interface_copy")]
    operations = [migrations.RunPython(add_default_images, migrations.RunPython.noop)]
