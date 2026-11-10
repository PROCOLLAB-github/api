from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django_rest_passwordreset.signals import reset_password_token_created

from users.models import CustomUser, Expert, Investor, Member, Mentor
from procollab.white_label import frontend_url, get_config


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


@receiver(post_save, sender=CustomUser)
def update_dataset_migration_applied(sender, instance, **kwargs):
    """Update the `dataset_migration_applied` attribute based on the presence of `v2_speciality` and `skills`."""

    def update_migration():
        dataset_migration_applied = bool(
            instance.v2_speciality and instance.skills.exists()
        )
        if instance.dataset_migration_applied != dataset_migration_applied:
            CustomUser.objects.filter(pk=instance.pk).update(
                dataset_migration_applied=dataset_migration_applied
            )

    # Delayed execution until transaction completes.
    transaction.on_commit(update_migration)


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, *args, **kwargs):
    brand = get_config()
    reset_password_url = (
        f"{frontend_url('https://app.procollab.ru')}/auth/reset_password/"
        f"?token={reset_password_token.key}"
    )
    registration_program = getattr(getattr(instance, "request", None), "data", {}).get(
        "registration_program_id"
    )
    if str(registration_program).isdigit() and len(str(registration_program)) <= 10:
        from partner_programs.models import PartnerProgram
        from urllib.parse import urlencode

        if PartnerProgram.objects.filter(
            pk=int(registration_program),
            draft=False,
            registration_config__published__mode="native",
        ).exists():
            reset_password_url = (
                frontend_url(settings.EXPERT_WORKSPACE_FRONTEND_URL)
                + "/program-password-reset/?"
                + urlencode(
                    {
                        "token": reset_password_token.key,
                        "registration_program": registration_program,
                    }
                )
            )
    # Invitation-specific return context; never accept an arbitrary redirect origin.
    invitation_token = getattr(getattr(instance, "request", None), "data", {}).get(
        "expert_invitation_token"
    )
    if invitation_token:
        from project_rates.workspace import token_invitation
        from rest_framework.exceptions import APIException
        from django.http import Http404
        from urllib.parse import urlencode

        try:
            invitation = token_invitation(invitation_token, allow_accepted=True)
        except (APIException, Http404):
            invitation = None
        if invitation and invitation.email == reset_password_token.user.email.lower():
            reset_password_url = (
                frontend_url(settings.EXPERT_WORKSPACE_FRONTEND_URL)
                + "/expert-password-reset/?"
                + urlencode(
                    {
                        "token": reset_password_token.key,
                        "expert_invitation": invitation_token,
                    }
                )
            )
    organizer_token = getattr(getattr(instance, "request", None), "data", {}).get(
        "organizer_invitation_token"
    )
    if organizer_token:
        from partner_programs.services.organizers import token_invitation
        from rest_framework.exceptions import APIException
        from django.http import Http404
        from urllib.parse import urlencode

        try:
            invitation = token_invitation(organizer_token, allow_accepted=True)
        except (APIException, Http404):
            invitation = None
        if (
            invitation
            and invitation.email.lower() == reset_password_token.user.email.lower()
        ):
            reset_password_url = (
                frontend_url(settings.EXPERT_WORKSPACE_FRONTEND_URL)
                + "/organizer-password-reset/?"
                + urlencode(
                    {
                        "token": reset_password_token.key,
                        "organizer_invitation": organizer_token,
                    }
                )
            )
    context = {
        "user": reset_password_token.user,
        "email": reset_password_token.user.email,
        "reset_password_url": reset_password_url,
        "brand_name": brand.brand_name,
    }

    template = "white_label_password_reset" if brand.enabled else "password_reset_email"
    email_html_message = render_to_string(f"email/{template}.html", context)
    email_plaintext_message = render_to_string(f"email/{template}.txt", context)

    msg = EmailMultiAlternatives(
        f"Сброс пароля | {brand.brand_name}"
        if brand.enabled
        else "Сброс пароля | Procollab",
        email_plaintext_message,
        settings.EMAIL_USER,
        [reset_password_token.user.email],
    )
    msg.attach_alternative(email_html_message, "text/html")
    msg.send()
