from django.core.mail import EmailMessage


class Email:
    @staticmethod
    def send_email(data):
        email = EmailMessage(
            subject=data["email_subject"], body=data["email_body"], to=[data["to_email"]]
        )
        email.send()
