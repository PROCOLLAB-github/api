from django.db.models.signals import post_save
from django.dispatch import receiver

from users.models import CustomUser, Member, Mentor, Expert, Investor


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

    # update ordering
    instance.ordering_score = instance.calculate_ordering_score()
