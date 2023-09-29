from django.core.mail import EmailMultiAlternatives
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django_rest_passwordreset.signals import reset_password_token_created

from users.models import CustomUser, Expert, Investor, Member, Mentor


@receiver(post_save, sender=CustomUser)
def create_or_update_user_types(sender, instance, created, **kwargs):
    if created:
        if instance.user_type == CustomUser.MEMBER:
            Member.objects.create(user=instance)
        elif instance.user_type == CustomUser.MENTOR:
            Mentor.objects.create(user=instance)
        elif instance.user_type == CustomUser.EXPERT:
            Expert.objects.create(user=instance)
        elif instance.user_type == CustomUser.INVESTOR:
            Investor.objects.create(user=instance)
    # check that the change wasn't about ordering scores
    current_ordering_score = instance.calculate_ordering_score()
    if instance.ordering_score != current_ordering_score:
        instance.ordering_score = current_ordering_score
        instance.save()


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, *args, **kwargs):
    reset_password_url = (
        f"https://app.procollab.ru/auth/reset_password/?token={reset_password_token.key}"
    )
    context = {
        "first_name": reset_password_token.user.first_name,
        "email": reset_password_token.user.email,
        "reset_password_url": reset_password_url,
    }

    # email_html_message = render_to_string("email/password_reset_email.html", context)
    # email_plaintext_message = render_to_string("email/password_reset_email.txt", context)
    email_html_message = render_to_string("email/reset-password.html", context)
    email_plaintext_message = render_to_string("email/reset-password.html", context)

    msg = EmailMultiAlternatives(
        "Сброс пароля | Procollab",
        email_plaintext_message,
        "procollab2022@gmail.com",
        [reset_password_token.user.email],
    )
    msg.attach_alternative(email_html_message, "text/html")
    msg.send()
