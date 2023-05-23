from django.core.mail import EmailMultiAlternatives


class Email:
    @staticmethod
    def send_email(data):
        email = EmailMultiAlternatives(
            subject=data["email_subject"],
            body=data["email_body"],
            to=[data["to_email"]],
        )
        if data.get("html_content"):
            email.attach_alternative(data["html_content"], "text/html")
        email.send()


def get_user_online_cache_key(user) -> str:
    return f"online_user_{user.pk}"
