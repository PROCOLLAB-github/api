import json
import logging
import requests
import socket
from django.conf import settings
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)


# todo: refactor this


def allow_alertmanager_only(view_func):
    def _wrapped_view(request, *args, **kwargs):
        alertmanager_ip = socket.gethostbyname("alertmanager")

        client_ip = request.META["REMOTE_ADDR"]
        print("abcd", client_ip, alertmanager_ip)
        if client_ip == alertmanager_ip:
            return view_func(request, *args, **kwargs)

        return HttpResponseForbidden("Forbidden")

    return _wrapped_view


@csrf_exempt
@allow_alertmanager_only
def alert_webhook(request):
    if request.method == "POST":
        try:
            payload = json.loads(request.body)
            for alert in payload["alerts"]:
                message = f"Alert: {alert['annotations']['summary']} - {alert['status']}"
                send_telegram_message(message)

                return JsonResponse({"status": "success"})
        except Exception as exc:
            logger.error(f"Failed to process alert {exc}", exc_info=exc)
            return JsonResponse({"status": "error"}, status=400)

    return JsonResponse({"status": "method not allowed"}, status=400)


def send_telegram_message(message):
    url = (
        f"https://api.telegram.org/bot{settings.ALERTMANAGER_TELEGRAM_TOKEN}/sendMessage"
    )
    data = {"chat_id": settings.ALERTMANAGER_TELEGRAM_CHAT_ID, "text": message}
    response = requests.post(url, data=data)
    return response.json()
