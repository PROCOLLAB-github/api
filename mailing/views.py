from django.http import JsonResponse

from users.models import CustomUser
from .utils import MailSender


def some_task(request):
    res = CustomUser.objects.all()
    MailSender.send(res, "test_subject", "password_reset_email.html")
    return JsonResponse({"kek": "lol"})
