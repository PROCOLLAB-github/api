from django.db import migrations


def create_board_and_column(apps, schema_editor):
    Board = apps.get_model("kanban", "Board")
    BoardColumn = apps.get_model("kanban", "BoardColumn")
    Project = apps.get_model("projects", "Project")

    for project in Project.objects.all():
        if Board.objects.filter(project=project).exists():
            continue
        board = Board.objects.create(project=project, name=project.name or "Канбан")
        BoardColumn.objects.create(board=board, name="Бэклог", order=1)


class Migration(migrations.Migration):
    dependencies = [
        ("kanban", "0003_taskcomment"),
    ]

    operations = [
        migrations.RunPython(create_board_and_column, migrations.RunPython.noop),
    ]
