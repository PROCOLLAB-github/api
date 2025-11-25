from django.db.models.signals import post_save
from django.dispatch import receiver

from kanban.models import Board, BoardColumn
from projects.models import Project


@receiver(post_save, sender=Project)
def create_default_board(sender, instance: Project, created: bool, **kwargs):
    if not created:
        return

    if Board.objects.filter(project=instance).exists():
        return

    board = Board.objects.create(project=instance, name=instance.name or "Канбан")
    BoardColumn.objects.create(board=board, name="Бэклог", order=1)
