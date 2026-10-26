from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from files.models import UserFile
from partner_programs.solution_files import used_by_submitted_solution


@receiver(pre_delete, sender=UserFile, dispatch_uid="protect_solution_snapshot_file")
def protect_snapshot_file(sender, instance, using, **kwargs):
    # Collector вызывает pre_delete в atomic; блокировка общая с PATCH/submit.
    sender.objects.using(using).select_for_update().filter(pk=instance.pk).first()
    if used_by_submitted_solution(instance.pk):
        raise ProtectedError("Файл используется в сохраненном решении.", [instance])
