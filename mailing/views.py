from django.http import JsonResponse

from .tasks import create_task


def some_task(request):
    create_task.delay(2)
    return JsonResponse({"kek": "lol"})
